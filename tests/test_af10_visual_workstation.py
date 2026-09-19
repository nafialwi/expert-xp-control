from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from xp.activity import (
    ActivityCategory,
    ActivityEvent,
    ActivityStatus,
    Provenance,
)
from xp.visual_workstation import (
    SnapshotStore,
    VisualActivity,
    VisualWorkstationSnapshot,
    render_terminal,
)


class AF10VisualWorkstationTests(unittest.TestCase):
    def test_snapshot_exposes_all_locked_visual_surfaces(self):
        snapshot = VisualWorkstationSnapshot(
            project="Segeran Jiwa POS Next",
            checkpoint="CS-04",
            recovery_status="READY",
            mode="WORKER",
            provider="hermes",
            model="agent",
            cost_state="FREE",
            worker="hermes",
            permission="GRANTED",
            approval="APPROVED",
            verification="PASS",
            rollback="NOT_PERFORMED",
            final_status="COMPLETED",
            live=False,
            activities=(),
        )
        data = snapshot.to_dict()
        for key in (
            "project",
            "checkpoint",
            "recovery_status",
            "mode",
            "provider",
            "model",
            "cost_state",
            "worker",
            "permission",
            "activities",
            "approval",
            "verification",
            "rollback",
            "live",
        ):
            self.assertIn(key, data)

    def test_activity_projection_excludes_metadata(self):
        event = ActivityEvent(
            event_id="e1",
            job_id="j1",
            timestamp=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
            category=ActivityCategory.AI,
            action="AI analysis",
            provenance=Provenance(
                source="README.md",
                processor="local:qwen",
                via="gateway",
                live=False,
            ),
            status=ActivityStatus.COMPLETED,
            result_summary="Analysis completed",
            metadata={
                "prompt": "PRIVATE_PROMPT",
                "token": "SECRET_TOKEN",
                "chain_of_thought": "HIDDEN",
            },
        )
        data = VisualActivity.from_event(event).to_dict()
        rendered = json.dumps(data)
        self.assertNotIn("PRIVATE_PROMPT", rendered)
        self.assertNotIn("SECRET_TOKEN", rendered)
        self.assertNotIn("HIDDEN", rendered)
        self.assertNotIn("metadata", data)

    def test_snapshot_store_roundtrip_and_default(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            store = SnapshotStore(path)
            default = store.read()
            self.assertEqual(default.final_status, "IDLE")

            snapshot = VisualWorkstationSnapshot.idle()
            store.write(snapshot)
            loaded = store.read()
            self.assertEqual(
                loaded.to_dict(),
                snapshot.to_dict(),
            )
            self.assertFalse(
                path.with_suffix(".json.tmp").exists()
            )

    def test_terminal_renderer_contains_human_visible_state(self):
        text = render_terminal(
            VisualWorkstationSnapshot.idle()
        )
        for label in (
            "Project",
            "Checkpoint",
            "Recovery",
            "Mode",
            "Provider",
            "Model",
            "Cost",
            "Worker",
            "Permission",
            "Approval",
            "Verification",
            "Rollback",
            "Status",
            "Source",
        ):
            self.assertIn(label, text)


if __name__ == "__main__":
    unittest.main()
