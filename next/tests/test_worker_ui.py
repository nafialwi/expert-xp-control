from __future__ import annotations

import unittest

from xp_next.worker_selection import (
    ConfirmationStatus,
    ResourceSnapshot,
    SelectionStatus,
    WorkerConfirmation,
    WorkerSelection,
)
from xp_next.worker_ui import (
    build_worker_choice_view,
    render_worker_choice,
    render_worker_confirmation,
)


class WorkerUITests(unittest.TestCase):
    def _selection(self) -> WorkerSelection:
        return WorkerSelection(
            status=SelectionStatus.RECOMMENDED,
            backend_id="lightweight_local",
            detail="bounded operation fits lightweight_local",
            explicit=False,
            requires_confirmation=True,
            considered_backends=("hermes", "lightweight_local"),
            resource_snapshot=ResourceSnapshot(
                available_memory_mb=1024,
                logical_cpus=4,
            ),
        )

    def test_human_view_contains_worker_reason_resources_and_choices(self):
        rendered = render_worker_choice(self._selection())
        self.assertIn("Worker yang disarankan: lightweight_local", rendered)
        self.assertIn("bounded operation fits lightweight_local", rendered)
        self.assertIn("1024 MiB", rendered)
        self.assertIn("4 logical CPU", rendered)
        self.assertIn("[1] Gunakan lightweight_local", rendered)
        self.assertIn("[0] Batal", rendered)

    def test_structured_view_does_not_hide_confirmation_requirement(self):
        view = build_worker_choice_view(self._selection())
        self.assertEqual(view.backend_id, "lightweight_local")
        self.assertTrue(view.confirmation_required)

    def test_confirmation_render_is_explicit(self):
        confirmed = WorkerConfirmation(
            status=ConfirmationStatus.CONFIRMED,
            backend_id="lightweight_local",
            detail="fresh exact-backend validation passed",
            resource_snapshot=ResourceSnapshot(
                available_memory_mb=1024,
                logical_cpus=4,
            ),
            selection_status=SelectionStatus.RECOMMENDED,
        )
        rendered = render_worker_confirmation(confirmed)
        self.assertIn("Worker dikonfirmasi: lightweight_local", rendered)
        self.assertIn("CONFIRMED", rendered)


if __name__ == "__main__":
    unittest.main()
