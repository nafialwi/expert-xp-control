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


if __name__ == "__main__":
    unittest.main()
