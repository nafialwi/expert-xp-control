from __future__ import annotations

import json
import unittest

from xp_next.job_state import JobState
from xp_next.work_session import (
    WorkAction,
    WorkSessionSnapshot,
    allowed_actions,
    public_session,
)


class WorkSessionContractTests(unittest.TestCase):
    def test_waiting_worker_allows_only_confirm_or_decline(self):
        self.assertEqual(
            allowed_actions(JobState.AWAITING_APPROVAL, {}),
            (WorkAction.CONFIRM_WORKER, WorkAction.DECLINE_WORKER),
        )

    def test_confirmed_worker_waiting_sandbox_allows_only_sandbox_decision(self):
        payload = {
            "worker_confirmation": {
                "status": "CONFIRMED",
                "backend_id": "lightweight_local",
            }
        }
        self.assertEqual(
            allowed_actions(JobState.AWAITING_APPROVAL, payload),
            (WorkAction.APPROVE_SANDBOX, WorkAction.DECLINE_SANDBOX),
        )

    def test_approved_sandbox_allows_only_execute(self):
        payload = {
            "worker_confirmation": {
                "status": "CONFIRMED",
                "backend_id": "lightweight_local",
            },
            "sandbox_approved": True,
        }
        self.assertEqual(
            allowed_actions(JobState.AWAITING_APPROVAL, payload),
            (WorkAction.EXECUTE,),
        )

    def test_ready_to_review_allows_only_apply_and_discard(self):
        payload = {
            "worker_confirmation": {"status": "CONFIRMED"},
            "sandbox_approved": True,
            "review": {
                "status": "PASS",
                "change_fingerprint": "abc",
            },
        }
        self.assertEqual(
            allowed_actions(JobState.READY_TO_REVIEW, payload),
            (WorkAction.APPLY, WorkAction.DISCARD),
        )

    def test_failure_and_terminal_states_have_no_mutating_actions(self):
        for state in (
            JobState.NEEDS_ATTENTION,
            JobState.CANCELLED,
            JobState.COMPLETED,
            JobState.ROLLED_BACK,
        ):
            with self.subTest(state=state.value):
                self.assertEqual(allowed_actions(state, {}), ())

    def test_projection_excludes_internal_fields_and_keeps_visible_review(self):
        snapshot = WorkSessionSnapshot(
            job={
                "id": "j1",
                "project_id": "p1",
                "user_goal": "fix it",
                "state": "READY_TO_REVIEW",
            },
            session={
                "job_id": "j1",
                "revision": 4,
                "payload": {
                    "project_name": "Fixture",
                    "worker_prompt": "PRIVATE_PROMPT",
                    "sandbox_root": "/private/sandbox",
                    "verifier": {
                        "name": "verify",
                        "argv": ["python", "-c", "SECRET"],
                    },
                    "worker_selection": {
                        "status": "RECOMMENDED",
                        "backend_id": "lightweight_local",
                        "detail": "bounded operation",
                        "resource_snapshot": {
                            "available_memory_mb": 512,
                            "logical_cpus": 2,
                        },
                    },
                    "worker_confirmation": {
                        "status": "CONFIRMED",
                        "backend_id": "lightweight_local",
                    },
                    "sandbox_approved": True,
                    "review": {
                        "status": "PASS",
                        "summary": "All configured verifiers passed.",
                        "changed_files": ["app.txt"],
                        "bounded_diff": "diff --git a/app.txt b/app.txt",
                        "diff_truncated": False,
                        "change_fingerprint": "abc",
                    },
                    "apply_status": None,
                    "recovery_ref": None,
                    "token": "SECRET_TOKEN",
                    "chain_of_thought": "HIDDEN",
                },
                "created_at": "now",
                "updated_at": "now",
            },
            activities=(
                {
                    "action": "verify",
                    "status": "Selesai",
                    "summary": "Verification PASS",
                    "source": "verifier",
                    "processor": "local",
                    "live": 0,
                    "created_at": "now",
                },
            ),
        )

        data = public_session(snapshot)
        rendered = json.dumps(data)

        self.assertEqual(data["id"], "j1")
        self.assertEqual(data["project"]["name"], "Fixture")
        self.assertEqual(data["state"], "READY_TO_REVIEW")
        self.assertEqual(data["review"]["changed_files"], ["app.txt"])
        self.assertEqual(
            data["allowed_actions"],
            ["APPLY", "DISCARD"],
        )
        self.assertNotIn("PRIVATE_PROMPT", rendered)
        self.assertNotIn("/private/sandbox", rendered)
        self.assertNotIn("SECRET_TOKEN", rendered)
        self.assertNotIn("HIDDEN", rendered)
        self.assertNotIn('"argv"', rendered)
        self.assertNotIn("worker_prompt", rendered)
        self.assertNotIn("sandbox_root", rendered)

    def test_snapshot_rejects_non_object_payload(self):
        snapshot = WorkSessionSnapshot(
            job={
                "id": "j1",
                "project_id": "p1",
                "user_goal": "goal",
                "state": "DRAFT",
            },
            session={
                "job_id": "j1",
                "revision": 1,
                "payload": "not-an-object",
            },
            activities=(),
        )
        with self.assertRaisesRegex(ValueError, "session payload must be an object"):
            _ = snapshot.payload

import sys
import tempfile
from pathlib import Path

from next.tests.test_zero_cost_e2e import LoopbackFixtureServer, init_source
from xp_next.local_qwen import LocalQwenAdapter
from xp_next.lightweight_worker import LightweightLocalWorker
from xp_next.planner import BoundedReadOnlyPlanner
from xp_next.project_service import ProjectService
from xp_next.runtime_paths import RuntimePaths
from xp_next.state_store import StateStore, StateStoreError
from xp_next.worker_selection import ResourceSnapshot, WorkerSelector
from xp_next.zero_cost_e2e import ReviewAction
from xp_next.work_session_service import WorkSessionService


class CountingWorker:
    def __init__(self):
        self.inner = LightweightLocalWorker()
        self.run_count = 0

    def readiness(self):
        return self.inner.readiness()

    def run(self, *args, **kwargs):
        self.run_count += 1
        return self.inner.run(*args, **kwargs)


class WorkSessionServiceTests(unittest.TestCase):
    def _verifier_command(self) -> str:
        code = (
            "from pathlib import Path; "
            "assert Path('app.txt').read_text() == 'CHANGED\\n'"
        )
        return f'{sys.executable} -c "{code}"'

    def _prompt(self) -> str:
        return json.dumps(
            {
                "operation": "replace_text",
                "path": "app.txt",
                "expected_text": "SAFE\n",
                "new_text": "CHANGED\n",
            }
        )

    def _build(
        self,
        base: Path,
        server: LoopbackFixtureServer,
        *,
        worker: CountingWorker | None = None,
        reopen: bool = False,
    ):
        source = base / "source"
        if not reopen:
            init_source(source)
        paths = RuntimePaths.resolve(base / "runtime").ensure()
        store = StateStore(paths.database)
        projects = ProjectService(store)
        if not reopen:
            projects.register(
                "fixture",
                "Fixture Project",
                source,
                source_kind="git",
            )
        selected_worker = worker or CountingWorker()
        workers = {"lightweight_local": selected_worker}
        selector = WorkerSelector(workers)
        service = WorkSessionService(
            store=store,
            projects=projects,
            paths=paths,
            reasoner=LocalQwenAdapter(
                base_url=server.base_url,
                model="qwen-fixture-local",
                timeout=5,
            ),
            planner=BoundedReadOnlyPlanner(),
            workers=workers,
            selector=selector,
            resource_probe=lambda: ResourceSnapshot(
                available_memory_mb=512,
                logical_cpus=2,
            ),
        )
        return source, store, service, selected_worker

    def _create(self, service: WorkSessionService):
        return service.create(
            job_id="visual-1",
            project_id="fixture",
            goal="replace SAFE with CHANGED",
            worker_prompt=self._prompt(),
            verifier_command=self._verifier_command(),
        )

    def _approve_to_execute(self, service: WorkSessionService):
        snapshot = self._create(service)
        self.assertEqual(snapshot.state, JobState.AWAITING_APPROVAL)
        self.assertEqual(
            snapshot.allowed_actions,
            (WorkAction.CONFIRM_WORKER, WorkAction.DECLINE_WORKER),
        )
        snapshot = service.decide_worker(
            "visual-1",
            backend_id="lightweight_local",
            approved=True,
            expected_revision=snapshot.revision,
        )
        self.assertEqual(
            snapshot.allowed_actions,
            (WorkAction.APPROVE_SANDBOX, WorkAction.DECLINE_SANDBOX),
        )
        snapshot = service.decide_sandbox(
            "visual-1",
            approved=True,
            expected_revision=snapshot.revision,
        )
        self.assertEqual(snapshot.allowed_actions, (WorkAction.EXECUTE,))
        return snapshot

    def test_create_prepares_project_and_exposes_visible_worker_recommendation(self):
        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as server:
            _, store, service, _ = self._build(Path(td), server)
            try:
                snapshot = self._create(service)
                self.assertEqual(snapshot.state, JobState.AWAITING_APPROVAL)
                self.assertEqual(
                    snapshot.payload["worker_selection"]["backend_id"],
                    "lightweight_local",
                )
                self.assertEqual(snapshot.payload["project_name"], "Fixture Project")
                self.assertNotIn("worker_confirmation", snapshot.payload)
            finally:
                store.close()

    def test_worker_and_sandbox_decisions_are_resumable_and_stale_revision_fails(self):
        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as server:
            _, store, service, _ = self._build(Path(td), server)
            try:
                created = self._create(service)
                approved = service.decide_worker(
                    "visual-1",
                    backend_id="lightweight_local",
                    approved=True,
                    expected_revision=created.revision,
                )
                with self.assertRaisesRegex(
                    StateStoreError,
                    "work session revision changed; refresh state",
                ):
                    service.decide_worker(
                        "visual-1",
                        backend_id="lightweight_local",
                        approved=True,
                        expected_revision=created.revision,
                    )
                worker_approvals = [
                    row
                    for row in store.list_approvals("visual-1")
                    if row["approval_class"] == "worker_selection"
                ]
                self.assertEqual(len(worker_approvals), 1)

                sandbox = service.decide_sandbox(
                    "visual-1",
                    approved=True,
                    expected_revision=approved.revision,
                )
                self.assertTrue(sandbox.payload["sandbox_approved"])
            finally:
                store.close()

    def test_execute_reaches_ready_to_review_and_keeps_original_unchanged(self):
        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as server:
            source, store, service, worker = self._build(Path(td), server)
            try:
                before = self._approve_to_execute(service)
                reviewed = service.execute(
                    "visual-1",
                    expected_revision=before.revision,
                )
                self.assertEqual(reviewed.state, JobState.READY_TO_REVIEW)
                self.assertEqual(reviewed.payload["review"]["status"], "PASS")
                self.assertEqual(
                    reviewed.allowed_actions,
                    (WorkAction.APPLY, WorkAction.DISCARD),
                )
                self.assertEqual(worker.run_count, 1)
                self.assertEqual((source / "app.txt").read_text(), "SAFE\n")
            finally:
                store.close()

    def test_restart_at_review_discards_without_rerunning_worker(self):
        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as server:
            base = Path(td)
            source, store, service, worker = self._build(base, server)
            before = self._approve_to_execute(service)
            reviewed = service.execute(
                "visual-1",
                expected_revision=before.revision,
            )
            review_revision = reviewed.revision
            fingerprint = reviewed.payload["review"]["change_fingerprint"]
            self.assertEqual(worker.run_count, 1)
            store.close()

            source2, reopened_store, reopened, same_worker = self._build(
                base,
                server,
                worker=worker,
                reopen=True,
            )
            try:
                loaded = reopened.get("visual-1")
                self.assertEqual(loaded.state, JobState.READY_TO_REVIEW)
                self.assertEqual(loaded.revision, review_revision)
                result = reopened.decide_review(
                    "visual-1",
                    action=ReviewAction.DISCARD,
                    fingerprint=str(fingerprint),
                    expected_revision=loaded.revision,
                )
                self.assertEqual(result.state, JobState.CANCELLED)
                self.assertEqual(result.payload["apply_status"], "DISCARDED")
                self.assertEqual(same_worker.run_count, 1)
                self.assertEqual((source2 / "app.txt").read_text(), "SAFE\n")
            finally:
                reopened_store.close()

    def test_missing_sandbox_after_review_fails_closed(self):
        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as server:
            source, store, service, _ = self._build(Path(td), server)
            try:
                before = self._approve_to_execute(service)
                reviewed = service.execute(
                    "visual-1",
                    expected_revision=before.revision,
                )
                sandbox_root = Path(str(reviewed.payload["sandbox_root"]))
                fingerprint = str(
                    reviewed.payload["review"]["change_fingerprint"]
                )
                import shutil
                shutil.rmtree(sandbox_root.parent)

                result = service.decide_review(
                    "visual-1",
                    action=ReviewAction.APPLY,
                    fingerprint=fingerprint,
                    expected_revision=reviewed.revision,
                )
                self.assertEqual(result.state, JobState.NEEDS_ATTENTION)
                self.assertIsNone(result.payload["apply_status"])
                self.assertEqual((source / "app.txt").read_text(), "SAFE\n")
            finally:
                store.close()

    def test_visual_project_projection_is_bounded_and_selectable(self):
        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as server:
            base = Path(td)
            _, store, service, _ = self._build(base, server)
            try:
                second = base / "second"
                init_source(second)
                service.projects.register(
                    "second",
                    "Second Project",
                    second,
                    source_kind="git",
                )
                projects = service.list_visual_projects()
                self.assertEqual(
                    {item["id"] for item in projects},
                    {"fixture", "second"},
                )
                rendered = json.dumps(projects)
                self.assertNotIn("root_path", rendered)
                self.assertNotIn("files", rendered)
                self.assertTrue(all("git" in item for item in projects))

                selected = service.select_visual_project("second")
                self.assertEqual(selected["id"], "second")
                self.assertTrue(selected["active"])
                self.assertEqual(
                    service.projects.current()["id"],
                    "second",
                )
            finally:
                store.close()

    def test_visual_snapshot_uses_latest_session_without_internal_secrets(self):
        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as server:
            _, store, service, _ = self._build(Path(td), server)
            try:
                service.projects.switch("fixture")
                self._create(service)
                snapshot = service.visual_snapshot()
                self.assertEqual(snapshot["product"], "XP Next")
                self.assertEqual(snapshot["active_project"]["id"], "fixture")
                self.assertEqual(snapshot["latest_session"]["id"], "visual-1")
                self.assertIn("capabilities", snapshot)
                rendered = json.dumps(snapshot)
                self.assertNotIn("worker_prompt", rendered)
                self.assertNotIn("PRIVATE_PROMPT", rendered)
                self.assertNotIn("sandbox_root", rendered)
            finally:
                store.close()

    def test_public_activity_is_allowlisted_and_clamped_to_fifty(self):
        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as server:
            _, store, service, _ = self._build(Path(td), server)
            try:
                self._create(service)
                for index in range(60):
                    store.record_activity(
                        f"visual-1:extra:{index:02d}",
                        job_id="visual-1",
                        category="test",
                        action=f"action-{index}",
                        status="Selesai",
                        summary=f"safe summary {index}",
                        source="fixture",
                        processor="test",
                        live=False,
                    )
                events = service.public_activity("visual-1", limit=1000)
                self.assertEqual(len(events), 50)
                rendered = json.dumps(events)
                self.assertNotIn("worker_prompt", rendered)
                self.assertNotIn("metadata", rendered)
                for event in events:
                    self.assertEqual(
                        set(event),
                        {
                            "action",
                            "status",
                            "summary",
                            "source",
                            "processor",
                            "live",
                            "created_at",
                        },
                    )
                with self.assertRaises(ValueError):
                    service.public_activity("visual-1", limit=0)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
