from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from next.tests.test_zero_cost_e2e import (
    LoopbackFixtureServer,
    git,
    init_source,
)

from xp_next.local_qwen import LocalQwenAdapter
from xp_next.lightweight_worker import LightweightLocalWorker
from xp_next.planner import BoundedReadOnlyPlanner
from xp_next.project_service import ProjectService
from xp_next.runtime_paths import RuntimePaths
from xp_next.sandbox_review import ReviewStatus, VerifierSpec
from xp_next.state_store import StateStore
from xp_next.worker_selection import (
    HumanWorkerConfirmation,
    ResourceSnapshot,
    WorkerSelectionRequest,
    WorkerSelector,
    confirm_worker_selection,
)
from xp_next.zero_cost_e2e import (
    HumanReviewDecision,
    PendingReviewResult,
    ReviewAction,
    ZeroCostE2EService,
)


def verifier() -> VerifierSpec:
    return VerifierSpec(
        name="fixture-content",
        argv=(
            "python",
            "-c",
            (
                "from pathlib import Path; "
                "assert Path('app.txt').read_text() == 'CHANGED\\n'"
            ),
        ),
    )


def prompt() -> str:
    return json.dumps(
        {
            "operation": "replace_text",
            "path": "app.txt",
            "expected_text": "SAFE\n",
            "new_text": "CHANGED\n",
        }
    )


class CP09BExecutionPhaseTests(unittest.TestCase):
    def _arrange(self, base: Path, server: LoopbackFixtureServer):
        source = base / "source"
        original_head = init_source(source)
        paths = RuntimePaths.resolve(base / "runtime").ensure()
        store = StateStore(paths.database)
        projects = ProjectService(store)
        projects.register(
            "fixture",
            "Fixture Project",
            source,
            source_kind="git",
        )
        worker = LightweightLocalWorker()
        reasoner = LocalQwenAdapter(
            base_url=server.base_url,
            model="qwen-fixture-local",
            timeout=5,
        )
        service = ZeroCostE2EService(
            store=store,
            projects=projects,
            paths=paths,
            reasoner=reasoner,
            planner=BoundedReadOnlyPlanner(),
            worker=worker,
        )

        worker_prompt = prompt()
        resources = ResourceSnapshot(
            available_memory_mb=512,
            logical_cpus=2,
        )
        selector = WorkerSelector({"lightweight_local": worker})
        request = WorkerSelectionRequest(worker_prompt=worker_prompt)
        selection = selector.select(request, resources=resources)
        confirmation = confirm_worker_selection(
            selector,
            selection=selection,
            request=request,
            confirmation=HumanWorkerConfirmation(
                backend_id="lightweight_local",
                approved=True,
            ),
            resources=resources,
        )

        store.create_job(
            "cp09b-review",
            "fixture",
            "Change the bounded fixture locally.",
            risk="write",
        )
        store.transition_job("cp09b-review", __import__(
            "xp_next.job_state", fromlist=["JobState"]
        ).JobState.PLANNING)
        store.transition_job("cp09b-review", __import__(
            "xp_next.job_state", fromlist=["JobState"]
        ).JobState.READY)
        store.transition_job("cp09b-review", __import__(
            "xp_next.job_state", fromlist=["JobState"]
        ).JobState.AWAITING_APPROVAL)
        store.record_approval(
            "cp09b-review:approval:worker",
            job_id="cp09b-review",
            approval_class="worker_selection",
            granted=True,
        )
        store.record_approval(
            "cp09b-review:approval:sandbox",
            job_id="cp09b-review",
            approval_class="sandbox_write",
            granted=True,
        )
        return (
            source,
            original_head,
            store,
            service,
            worker_prompt,
            selection,
            confirmation,
        )

    def _pending(self, base: Path, server: LoopbackFixtureServer):
        arranged = self._arrange(base, server)
        source, original_head, store, service, worker_prompt, selection, confirmation = arranged
        pending = service.execute_existing_to_review(
            job_id="cp09b-review",
            project_id="fixture",
            goal="Change the bounded fixture locally.",
            worker_prompt=worker_prompt,
            verifier_specs=(verifier(),),
            worker_selection=selection,
            worker_confirmation=confirmation,
        )
        self.assertIsInstance(pending, PendingReviewResult)
        assert isinstance(pending, PendingReviewResult)
        return source, original_head, store, service, pending

    def test_execute_existing_job_pauses_at_ready_to_review_without_source_mutation(self):
        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as server:
            source, original_head, store, service, pending = self._pending(
                Path(td), server
            )
            try:
                self.assertEqual(
                    store.get_job("cp09b-review")["state"],
                    "READY_TO_REVIEW",
                )
                self.assertEqual(pending.review.status, ReviewStatus.PASS)
                self.assertEqual(pending.review.changed_files, ("app.txt",))
                self.assertEqual((source / "app.txt").read_text(), "SAFE\n")
                self.assertEqual(git(source, "rev-parse", "HEAD"), original_head)
                self.assertEqual(
                    (Path(pending.sandbox_root) / "app.txt").read_text(),
                    "CHANGED\n",
                )
            finally:
                store.close()

    def test_finalize_discard_resumes_without_mutating_original(self):
        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as server:
            source, _, store, service, pending = self._pending(Path(td), server)
            try:
                result = service.finalize_existing_review(
                    pending=pending,
                    decision=HumanReviewDecision(
                        action=ReviewAction.DISCARD,
                        approved_change_fingerprint=pending.review.change_fingerprint,
                    ),
                    verifier_specs=(verifier(),),
                )
                self.assertEqual(result.job_state, "CANCELLED")
                self.assertEqual(result.apply_status, "DISCARDED")
                self.assertEqual((source / "app.txt").read_text(), "SAFE\n")
            finally:
                store.close()

    def test_fingerprint_mismatch_fails_closed_before_apply(self):
        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as server:
            source, _, store, service, pending = self._pending(Path(td), server)
            try:
                result = service.finalize_existing_review(
                    pending=pending,
                    decision=HumanReviewDecision(
                        action=ReviewAction.APPLY,
                        approved_change_fingerprint="stale-fingerprint",
                    ),
                    verifier_specs=(verifier(),),
                )
                self.assertEqual(result.job_state, "NEEDS_ATTENTION")
                self.assertIsNone(result.apply_status)
                self.assertEqual((source / "app.txt").read_text(), "SAFE\n")
            finally:
                store.close()

    def test_original_head_drift_blocks_apply_without_overwrite(self):
        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as server:
            source, original_head, store, service, pending = self._pending(
                Path(td), server
            )
            try:
                (source / "drift.txt").write_text("DRIFT\n", encoding="utf-8")
                git(source, "add", "drift.txt")
                git(source, "commit", "-qm", "drift")
                drift_head = git(source, "rev-parse", "HEAD")
                self.assertNotEqual(drift_head, original_head)

                result = service.finalize_existing_review(
                    pending=pending,
                    decision=HumanReviewDecision(
                        action=ReviewAction.APPLY,
                        approved_change_fingerprint=pending.review.change_fingerprint,
                    ),
                    verifier_specs=(verifier(),),
                )
                self.assertEqual(result.job_state, "NEEDS_ATTENTION")
                self.assertNotEqual(result.apply_status, "APPLIED")
                self.assertEqual((source / "app.txt").read_text(), "SAFE\n")
                self.assertEqual(git(source, "rev-parse", "HEAD"), drift_head)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
