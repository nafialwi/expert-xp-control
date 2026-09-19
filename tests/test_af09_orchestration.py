from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from xp.activity import ActivityStore
from xp.capabilities import CapabilityState
from xp.ai.hybrid_routing import (
    CandidateKind,
    HybridCandidate,
    HybridMode,
    QuotaState,
    RouteLocality,
    TaskKind,
)
from xp.orchestration import (
    BoundedPlan,
    ContextItem,
    ExecutionReport,
    OrchestrationRequest,
    OrchestrationStatus,
    PlanStep,
    ProjectOrchestrator,
    ProjectRef,
    VerificationReport,
)


def local_ai():
    return HybridCandidate(
        candidate_id="local-ai",
        kind=CandidateKind.AI,
        provider="local",
        model="qwen-test",
        locality=RouteLocality.LOCAL,
        cost_class="free",
        readiness=CapabilityState.AVAILABLE,
        quota=QuotaState.OK,
        privacy_safe=True,
    )


def local_worker(permission=True):
    return HybridCandidate(
        candidate_id="local-worker",
        kind=CandidateKind.WORKER,
        provider="worker",
        model="fake-runtime",
        locality=RouteLocality.LOCAL,
        cost_class="free",
        readiness=CapabilityState.AVAILABLE,
        quota=QuotaState.OK,
        permission_granted=permission,
    )


def project(root):
    return ProjectRef(
        project_id="dummy",
        name="Dummy",
        root=root,
        checkpoint="BASE",
    )


def read_context(req):
    return (
        ContextItem(
            path=req.project.root / "README.md",
            kind="doc",
            summary="project readme",
        ),
    )


def read_plan(_req, _context):
    return BoundedPlan(
        steps=(
            PlanStep(
                step_id="inspect",
                action="inspect selected context",
            ),
        )
    )


class AF09OrchestrationTests(unittest.TestCase):
    def test_read_only_analysis_selects_context_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text("hello", encoding="utf-8")
            store = ActivityStore(root / ".trail")

            result = ProjectOrchestrator(
                activity_store=store
            ).run(
                OrchestrationRequest(
                    job_id="job-read",
                    message="Analyze this project",
                    project=project(root),
                    task_kind=TaskKind.SOURCE_ANALYSIS,
                    mode=HybridMode.ANALYSIS,
                    candidates=(local_ai(),),
                    selected_candidate_id="local-ai",
                ),
                retriever=read_context,
                planner=read_plan,
                executor=lambda *_: ExecutionReport(
                    True, "analysis completed"
                ),
                verifier=lambda *_: VerificationReport(
                    True, "analysis verified"
                ),
                checkpoint_writer=lambda *_: "READ-OK",
            )

            self.assertIs(
                result.status,
                OrchestrationStatus.COMPLETED,
            )
            self.assertEqual(result.context_paths, ("README.md",))
            self.assertEqual(result.final_checkpoint, "READ-OK")
            actions = {
                event.action
                for event in store.list_for_job("job-read")
            }
            for required in (
                "Project identified",
                "Context retrieval",
                "Bounded plan",
                "Route decision",
                "Execution",
                "Verifier",
                "Checkpoint",
            ):
                self.assertIn(required, actions)

    def test_context_outside_project_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "project"
            root.mkdir()
            outside = base / "outside.txt"
            (root / "README.md").write_text("x", encoding="utf-8")
            outside.write_text("secret", encoding="utf-8")
            request = OrchestrationRequest(
                job_id="job-boundary",
                message="Analyze",
                project=project(root),
                task_kind=TaskKind.SOURCE_ANALYSIS,
                mode=HybridMode.ANALYSIS,
                candidates=(local_ai(),),
                selected_candidate_id="local-ai",
            )
            with self.assertRaisesRegex(ValueError, "inside project root"):
                ProjectOrchestrator().run(
                    request,
                    retriever=lambda _req: (
                        ContextItem(
                            path=outside,
                            kind="file",
                            summary="outside",
                        ),
                    ),
                    planner=read_plan,
                    executor=lambda *_: ExecutionReport(True, "x"),
                    verifier=lambda *_: VerificationReport(True, "x"),
                )

    def test_plan_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "bounded step limit"):
            BoundedPlan(
                steps=tuple(
                    PlanStep(step_id=f"s{i}", action="x")
                    for i in range(9)
                )
            )

    def test_mutation_without_approval_is_blocked_before_executor(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text("x", encoding="utf-8")
            calls = []
            result = ProjectOrchestrator().run(
                OrchestrationRequest(
                    job_id="job-block",
                    message="Change project",
                    project=project(root),
                    task_kind=TaskKind.CODE_MUTATION,
                    mode=HybridMode.WORKER,
                    candidates=(local_worker(permission=True),),
                    selected_candidate_id="local-worker",
                    approval_granted=False,
                ),
                retriever=read_context,
                planner=lambda *_: BoundedPlan(
                    steps=(
                        PlanStep(
                            step_id="write",
                            action="write",
                            requires_write=True,
                        ),
                    )
                ),
                executor=lambda *_: (
                    calls.append("called")
                    or ExecutionReport(True, "should not run")
                ),
                verifier=lambda *_: VerificationReport(True, "x"),
                recovery_factory=lambda _root: "recovery",
                rollback=lambda _rid: None,
            )
            self.assertIs(result.status, OrchestrationStatus.BLOCKED)
            self.assertEqual(calls, [])

    def test_write_creates_recovery_before_execution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text("x", encoding="utf-8")
            order = []

            def recovery(_root):
                order.append("recovery")
                return "R1"

            def execute(*_):
                order.append("execute")
                (root / "proof.txt").write_text("OK", encoding="utf-8")
                return ExecutionReport(
                    True, "proof written", ("proof.txt",)
                )

            result = ProjectOrchestrator().run(
                OrchestrationRequest(
                    job_id="job-write",
                    message="Write proof",
                    project=project(root),
                    task_kind=TaskKind.CODE_MUTATION,
                    mode=HybridMode.WORKER,
                    candidates=(local_worker(permission=True),),
                    selected_candidate_id="local-worker",
                    approval_granted=True,
                ),
                retriever=read_context,
                planner=lambda *_: BoundedPlan(
                    steps=(
                        PlanStep(
                            step_id="write",
                            action="write proof",
                            requires_write=True,
                        ),
                    )
                ),
                executor=execute,
                verifier=lambda path, _report: VerificationReport(
                    (path / "proof.txt").read_text(
                        encoding="utf-8"
                    ) == "OK",
                    "proof verified",
                ),
                recovery_factory=recovery,
                rollback=lambda _rid: order.append("rollback"),
                checkpoint_writer=lambda *_: "WRITE-OK",
            )

            self.assertEqual(order[:2], ["recovery", "execute"])
            self.assertIs(
                result.status,
                OrchestrationStatus.COMPLETED,
            )

    def test_failing_verifier_gets_one_bounded_remediation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text("x", encoding="utf-8")
            target = root / "proof.txt"

            def execute(*_):
                target.write_text("BAD", encoding="utf-8")
                return ExecutionReport(
                    True, "first write", ("proof.txt",)
                )

            def remediate(*_):
                target.write_text("GOOD", encoding="utf-8")
                return ExecutionReport(
                    True, "fixed write", ("proof.txt",)
                )

            result = ProjectOrchestrator(
                max_remediation=1
            ).run(
                OrchestrationRequest(
                    job_id="job-remediate",
                    message="Create verified proof",
                    project=project(root),
                    task_kind=TaskKind.CODE_MUTATION,
                    mode=HybridMode.WORKER,
                    candidates=(local_worker(permission=True),),
                    selected_candidate_id="local-worker",
                    approval_granted=True,
                ),
                retriever=read_context,
                planner=lambda *_: BoundedPlan(
                    steps=(
                        PlanStep(
                            step_id="write",
                            action="write proof",
                            requires_write=True,
                        ),
                    )
                ),
                executor=execute,
                verifier=lambda path, _report: VerificationReport(
                    (path / "proof.txt").read_text(
                        encoding="utf-8"
                    ) == "GOOD",
                    "proof must equal GOOD",
                ),
                recovery_factory=lambda _root: "R2",
                remediator=remediate,
                rollback=lambda _rid: None,
                checkpoint_writer=lambda *_: "REMEDIATED",
            )

            self.assertIs(
                result.status,
                OrchestrationStatus.COMPLETED,
            )
            self.assertEqual(result.attempts, 2)

    def test_exhausted_remediation_rolls_back(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text("x", encoding="utf-8")
            original = root / "original.txt"
            original.write_text("SAFE", encoding="utf-8")
            backup_dir = Path(tempfile.mkdtemp())
            self.addCleanup(shutil.rmtree, backup_dir)
            shutil.copy2(original, backup_dir / "original.txt")

            def bad(*_):
                original.write_text("BROKEN", encoding="utf-8")
                return ExecutionReport(
                    True, "bad", ("original.txt",)
                )

            def rollback(_rid):
                shutil.copy2(
                    backup_dir / "original.txt",
                    original,
                )

            result = ProjectOrchestrator(
                max_remediation=1
            ).run(
                OrchestrationRequest(
                    job_id="job-rollback",
                    message="Bad change",
                    project=project(root),
                    task_kind=TaskKind.CODE_MUTATION,
                    mode=HybridMode.WORKER,
                    candidates=(local_worker(permission=True),),
                    selected_candidate_id="local-worker",
                    approval_granted=True,
                ),
                retriever=read_context,
                planner=lambda *_: BoundedPlan(
                    steps=(
                        PlanStep(
                            step_id="write",
                            action="write",
                            requires_write=True,
                        ),
                    )
                ),
                executor=bad,
                verifier=lambda *_: VerificationReport(
                    False, "always failing"
                ),
                recovery_factory=lambda _root: "R3",
                remediator=bad,
                rollback=rollback,
            )

            self.assertIs(
                result.status,
                OrchestrationStatus.ROLLED_BACK,
            )
            self.assertTrue(result.rollback_performed)
            self.assertEqual(
                original.read_text(encoding="utf-8"),
                "SAFE",
            )

    def test_activity_trail_excludes_conversation_message(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text("x", encoding="utf-8")
            store = ActivityStore(root / ".trail")
            secret_message = "PRIVATE CONVERSATION PAYLOAD"
            ProjectOrchestrator(
                activity_store=store
            ).run(
                OrchestrationRequest(
                    job_id="job-private",
                    message=secret_message,
                    project=project(root),
                    task_kind=TaskKind.SOURCE_ANALYSIS,
                    mode=HybridMode.ANALYSIS,
                    candidates=(local_ai(),),
                    selected_candidate_id="local-ai",
                ),
                retriever=read_context,
                planner=read_plan,
                executor=lambda *_: ExecutionReport(True, "done"),
                verifier=lambda *_: VerificationReport(
                    True, "verified"
                ),
            )
            self.assertNotIn(
                secret_message,
                repr(store.list_for_job("job-private")),
            )


if __name__ == "__main__":
    unittest.main()
