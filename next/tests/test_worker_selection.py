from __future__ import annotations

import json
import unittest

from xp_next.lightweight_worker import LightweightLocalWorker
from xp_next.worker_contract import WorkerReadiness
from xp_next.worker_selection import (
    ResourceSnapshot,
    SelectionStatus,
    WorkerSelectionRequest,
    WorkerSelector,
)


class FakeHermes:
    def __init__(self, *, ready: bool = True, detail: str = "ready"):
        self.ready = ready
        self.detail = detail

    def readiness(self):
        return WorkerReadiness(
            ready=self.ready,
            status="READY" if self.ready else "NEEDS_ATTENTION",
            detail=self.detail,
            backend_id="hermes",
            model_transport="loopback_http",
            containment="isolated",
        )


class WorkerSelectionTests(unittest.TestCase):
    def _selector(self, *, hermes_ready: bool = True) -> WorkerSelector:
        return WorkerSelector(
            {
                "lightweight_local": LightweightLocalWorker(),
                "hermes": FakeHermes(ready=hermes_ready, detail="hermes fixture"),
            }
        )

    def _light_prompt(self) -> str:
        return json.dumps(
            {
                "operation": "replace_text",
                "path": "app.txt",
                "expected_text": "SAFE\n",
                "new_text": "CHANGED\n",
            }
        )

    def test_structured_lightweight_work_is_recommended_not_silently_selected(self):
        selection = self._selector().select(
            WorkerSelectionRequest(worker_prompt=self._light_prompt()),
            resources=ResourceSnapshot(available_memory_mb=512, logical_cpus=2),
        )
        self.assertEqual(selection.status, SelectionStatus.RECOMMENDED)
        self.assertEqual(selection.backend_id, "lightweight_local")
        self.assertFalse(selection.explicit)
        self.assertTrue(selection.requires_confirmation)

    def test_explicit_lightweight_selection_succeeds_when_compatible(self):
        selection = self._selector().select(
            WorkerSelectionRequest(
                worker_prompt=self._light_prompt(),
                requested_backend="lightweight_local",
            ),
            resources=ResourceSnapshot(available_memory_mb=128, logical_cpus=1),
        )
        self.assertEqual(selection.status, SelectionStatus.SELECTED)
        self.assertEqual(selection.backend_id, "lightweight_local")
        self.assertTrue(selection.explicit)
        self.assertFalse(selection.requires_confirmation)

    def test_explicit_lightweight_incompatible_prompt_does_not_fallback_to_hermes(self):
        selection = self._selector().select(
            WorkerSelectionRequest(
                worker_prompt="inspect the project and fix the bug",
                requested_backend="lightweight_local",
            ),
            resources=ResourceSnapshot(available_memory_mb=8192, logical_cpus=8),
        )
        self.assertEqual(selection.status, SelectionStatus.NEEDS_ATTENTION)
        self.assertIsNone(selection.backend_id)
        self.assertEqual(selection.considered_backends, ("lightweight_local",))
        self.assertIn("No fallback", selection.detail)

    def test_explicit_hermes_unready_does_not_fallback(self):
        selection = self._selector(hermes_ready=False).select(
            WorkerSelectionRequest(
                worker_prompt=self._light_prompt(),
                requested_backend="hermes",
            ),
            resources=ResourceSnapshot(available_memory_mb=8192, logical_cpus=8),
        )
        self.assertEqual(selection.status, SelectionStatus.NEEDS_ATTENTION)
        self.assertIsNone(selection.backend_id)
        self.assertEqual(selection.considered_backends, ("hermes",))
        self.assertIn("No fallback", selection.detail)

    def test_explicit_hermes_is_blocked_by_insufficient_memory(self):
        selection = self._selector().select(
            WorkerSelectionRequest(
                worker_prompt="agentic task",
                requested_backend="hermes",
            ),
            resources=ResourceSnapshot(available_memory_mb=2800, logical_cpus=4),
        )
        self.assertEqual(selection.status, SelectionStatus.NEEDS_ATTENTION)
        self.assertIn("4096 MiB", selection.detail)
        self.assertIn("No fallback", selection.detail)

    def test_agentic_task_can_only_be_recommended_when_resource_profile_passes(self):
        selection = self._selector().select(
            WorkerSelectionRequest(worker_prompt="agentic task"),
            resources=ResourceSnapshot(available_memory_mb=8192, logical_cpus=8),
        )
        self.assertEqual(selection.status, SelectionStatus.RECOMMENDED)
        self.assertEqual(selection.backend_id, "hermes")
        self.assertTrue(selection.requires_confirmation)

    def test_agentic_task_needs_attention_on_current_low_memory_shape(self):
        selection = self._selector().select(
            WorkerSelectionRequest(worker_prompt="agentic task"),
            resources=ResourceSnapshot(available_memory_mb=2048, logical_cpus=4),
        )
        self.assertEqual(selection.status, SelectionStatus.NEEDS_ATTENTION)
        self.assertIsNone(selection.backend_id)
        self.assertIn("no worker can be recommended safely", selection.detail)

    def test_unknown_explicit_backend_fails_closed(self):
        selection = self._selector().select(
            WorkerSelectionRequest(
                worker_prompt="task",
                requested_backend="other",
            ),
            resources=ResourceSnapshot(available_memory_mb=8192, logical_cpus=8),
        )
        self.assertEqual(selection.status, SelectionStatus.NEEDS_ATTENTION)
        self.assertIsNone(selection.backend_id)
        self.assertIn("unavailable", selection.detail)

    def test_resource_snapshot_validation(self):
        with self.assertRaises(ValueError):
            ResourceSnapshot(available_memory_mb=-1, logical_cpus=1)
        with self.assertRaises(ValueError):
            ResourceSnapshot(available_memory_mb=100, logical_cpus=0)


if __name__ == "__main__":
    unittest.main()
