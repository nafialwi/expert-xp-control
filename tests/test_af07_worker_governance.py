from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from xp.activity import ActivityStore
from xp.ai.agents.base import AgentReadiness, AgentRunRequest, AgentRunResult, AgentRuntime
from xp.worker_governance import (
    ApprovalClass,
    ApprovalGrant,
    ApprovalRequiredError,
    ExecutionRisk,
    ExecutionScope,
    GovernedWorker,
    ProtectedRepoMutationError,
    UnauthorizedMutationError,
    VerificationResult,
    WorkerNotReadyError,
    WorkspaceBoundaryError,
)


class FakeRuntime(AgentRuntime):
    def __init__(self, *, ready=True, mutate=False, fail_first=False, protected=None):
        self.ready_value = ready
        self.mutate = mutate
        self.fail_first = fail_first
        self.protected = protected
        self.run_calls = 0

    def name(self) -> str:
        return "fake-worker"

    def readiness(self):
        return AgentReadiness(
            ready=self.ready_value,
            status="READY" if self.ready_value else "NOT_READY",
            detail="fake runtime",
        )

    def run(self, request):
        self.run_calls += 1
        if self.protected is not None:
            (self.protected / "unexpected.txt").write_text("changed", encoding="utf-8")
        if self.mutate and request.cwd is not None:
            (request.cwd / "worker.txt").write_text(f"attempt={self.run_calls}", encoding="utf-8")
        if self.fail_first and self.run_calls == 1:
            return AgentRunResult(status="FAILED", output="first attempt failed", returncode=1)
        return AgentRunResult(status="OK", output="done", returncode=0)


def recovery_pair(root):
    backup_parent = Path(tempfile.mkdtemp())
    backup = backup_parent / "backup"
    shutil.copytree(root, backup)

    def create_recovery(_root):
        return str(backup)

    def rollback(recovery_id):
        source = Path(recovery_id)
        for child in list(root.iterdir()):
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        for child in source.iterdir():
            target = root / child.name
            if child.is_dir():
                shutil.copytree(child, target)
            else:
                shutil.copy2(child, target)

    return create_recovery, rollback


def grant(root, cls=ApprovalClass.WRITE_ALLOWED, approved=True):
    return ApprovalGrant(job_id="job-1", approval_class=cls, approved=approved, scope_root=root)


class AF07GovernedWorkerTests(unittest.TestCase):
    def test_cwd_outside_scope_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "root"
            outside = Path(td) / "outside"
            root.mkdir(); outside.mkdir()
            with self.assertRaises(WorkspaceBoundaryError):
                ExecutionScope(root=root, cwd=outside)

    def test_cwd_is_context_not_permission(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime = FakeRuntime()
            worker = GovernedWorker(runtime)
            create, rollback = recovery_pair(root)
            with self.assertRaises(ApprovalRequiredError):
                worker.execute(
                    job_id="job-1",
                    request=AgentRunRequest(prompt="x", cwd=root),
                    scope=ExecutionScope(root=root, cwd=root),
                    risk=ExecutionRisk.WRITE,
                    approval=grant(root, ApprovalClass.READ_ONLY),
                    verifier=lambda *_: VerificationResult(True, "ok"),
                    create_recovery=create,
                    rollback=rollback,
                )
            self.assertEqual(runtime.run_calls, 0)

    def test_high_risk_requires_high_risk_confirm(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime = FakeRuntime()
            worker = GovernedWorker(runtime)
            create, rollback = recovery_pair(root)
            with self.assertRaises(ApprovalRequiredError):
                worker.execute(
                    job_id="job-1",
                    request=AgentRunRequest(prompt="x", cwd=root),
                    scope=ExecutionScope(root=root, cwd=root),
                    risk=ExecutionRisk.HIGH_RISK,
                    approval=grant(root, ApprovalClass.WRITE_ALLOWED),
                    verifier=lambda *_: VerificationResult(True, "ok"),
                    create_recovery=create,
                    rollback=rollback,
                )

    def test_not_ready_blocks_before_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime = FakeRuntime(ready=False)
            worker = GovernedWorker(runtime)
            create, rollback = recovery_pair(root)
            with self.assertRaises(WorkerNotReadyError):
                worker.execute(
                    job_id="job-1",
                    request=AgentRunRequest(prompt="x", cwd=root),
                    scope=ExecutionScope(root=root, cwd=root),
                    risk=ExecutionRisk.WRITE,
                    approval=grant(root),
                    verifier=lambda *_: VerificationResult(True, "ok"),
                    create_recovery=create,
                    rollback=rollback,
                )
            self.assertEqual(runtime.run_calls, 0)

    def test_read_only_mutation_is_rolled_back(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "original.txt").write_text("safe", encoding="utf-8")
            runtime = FakeRuntime(mutate=True)
            worker = GovernedWorker(runtime)
            create, rollback = recovery_pair(root)
            with self.assertRaises(UnauthorizedMutationError):
                worker.execute(
                    job_id="job-1",
                    request=AgentRunRequest(prompt="inspect", cwd=root),
                    scope=ExecutionScope(root=root, cwd=root),
                    risk=ExecutionRisk.READ_ONLY,
                    approval=grant(root, ApprovalClass.READ_ONLY),
                    verifier=lambda *_: VerificationResult(True, "ok"),
                    create_recovery=create,
                    rollback=rollback,
                )
            self.assertFalse((root / "worker.txt").exists())
            self.assertEqual((root / "original.txt").read_text(encoding="utf-8"), "safe")

    def test_write_allowed_records_activity_without_raw_prompt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            activity_root = root / "activity"
            work = root / "work"
            work.mkdir()
            store = ActivityStore(activity_root)
            runtime = FakeRuntime(mutate=True)
            worker = GovernedWorker(runtime, activity_store=store, max_remediation=0)
            create, rollback = recovery_pair(work)
            result = worker.execute(
                job_id="job-1",
                request=AgentRunRequest(prompt="SUPER_SECRET_PROMPT_TEXT", cwd=work),
                scope=ExecutionScope(root=work, cwd=work),
                risk=ExecutionRisk.WRITE,
                approval=grant(work),
                verifier=lambda path, res: VerificationResult(
                    (path / "worker.txt").is_file() and res.returncode == 0,
                    "worker file verified",
                ),
                create_recovery=create,
                rollback=rollback,
            )
            self.assertEqual(result.status, "COMPLETED")
            self.assertEqual(result.attempts, 1)
            self.assertEqual([m.path for m in result.mutations], ["worker.txt"])
            events = store.list_for_job("job-1")
            actions = {e.action for e in events}
            for required in ("Worker approval", "Recovery point", "Mutation audit", "Verifier"):
                self.assertIn(required, actions)
            serialized = "\n".join(e.result_summary + repr(e.metadata) for e in events)
            self.assertNotIn("SUPER_SECRET_PROMPT_TEXT", serialized)

    def test_bounded_remediation_allows_only_one_retry(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime = FakeRuntime(mutate=True, fail_first=True)
            worker = GovernedWorker(runtime, max_remediation=1)
            create, rollback = recovery_pair(root)
            result = worker.execute(
                job_id="job-1",
                request=AgentRunRequest(prompt="repair", cwd=root),
                scope=ExecutionScope(root=root, cwd=root),
                risk=ExecutionRisk.WRITE,
                approval=grant(root),
                verifier=lambda _path, res: VerificationResult(
                    res.returncode == 0,
                    "pass" if res.returncode == 0 else "repair required",
                ),
                create_recovery=create,
                rollback=rollback,
            )
            self.assertEqual(result.status, "COMPLETED")
            self.assertEqual(result.attempts, 2)
            self.assertEqual(runtime.run_calls, 2)

    def test_exhausted_remediation_rolls_back(self):
        class AlwaysFail(FakeRuntime):
            def run(self, request):
                self.run_calls += 1
                (request.cwd / "broken.txt").write_text("broken", encoding="utf-8")
                return AgentRunResult(status="FAILED", output="failed", returncode=1)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "original.txt").write_text("safe", encoding="utf-8")
            runtime = AlwaysFail()
            worker = GovernedWorker(runtime, max_remediation=1)
            create, rollback = recovery_pair(root)
            result = worker.execute(
                job_id="job-1",
                request=AgentRunRequest(prompt="repair", cwd=root),
                scope=ExecutionScope(root=root, cwd=root),
                risk=ExecutionRisk.WRITE,
                approval=grant(root),
                verifier=lambda *_: VerificationResult(False, "still failing"),
                create_recovery=create,
                rollback=rollback,
            )
            self.assertEqual(result.status, "NEEDS_ATTENTION")
            self.assertEqual(result.attempts, 2)
            self.assertTrue(result.rollback_performed)
            self.assertFalse((root / "broken.txt").exists())

    def test_protected_repo_mutation_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            work = tmp / "work"; protected = tmp / "protected"
            work.mkdir(); protected.mkdir()
            subprocess.run(["git", "init", str(protected)], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", str(protected), "config", "user.email", "af07@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(protected), "config", "user.name", "AF07 Test"], check=True)
            (protected / "keep.txt").write_text("keep", encoding="utf-8")
            subprocess.run(["git", "-C", str(protected), "add", "keep.txt"], check=True)
            subprocess.run(["git", "-C", str(protected), "commit", "-m", "base"], check=True, stdout=subprocess.DEVNULL)
            runtime = FakeRuntime(protected=protected)
            worker = GovernedWorker(runtime, protected_repo=protected, max_remediation=0)
            create, rollback = recovery_pair(work)
            with self.assertRaises(ProtectedRepoMutationError):
                worker.execute(
                    job_id="job-1",
                    request=AgentRunRequest(prompt="x", cwd=work),
                    scope=ExecutionScope(root=work, cwd=work),
                    risk=ExecutionRisk.WRITE,
                    approval=grant(work),
                    verifier=lambda *_: VerificationResult(True, "ok"),
                    create_recovery=create,
                    rollback=rollback,
                )


if __name__ == "__main__":
    unittest.main()
