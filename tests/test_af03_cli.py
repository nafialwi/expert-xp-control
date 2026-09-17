from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from xp.activity import (
    ActivityCategory,
    ActivityEvent,
    ActivityStatus,
    ActivityStore,
    Provenance,
)
from xp.capabilities import (
    CapabilitySnapshot,
    CapabilityState,
)
from xp.cli import main


FIXED = datetime(
    2026, 9, 17, 14, 30,
    tzinfo=timezone.utc,
)


class FakeLiveService:
    def __init__(self):
        self.calls = 0

    def run_explicit(self):
        self.calls += 1

        return (
            CapabilitySnapshot(
                capability_id="ai:primary",
                state=CapabilityState.AVAILABLE,
                detail="AI route ready",
                checked_at=FIXED,
                live=True,
                metadata={
                    "route_id": "primary",
                },
            ),
        )


class AF03CheckCLITests(unittest.TestCase):
    def test_plain_check_never_builds_live_service(self):
        output = io.StringIO()

        with (
            patch(
                "xp.cli._build_live_check_service",
                side_effect=AssertionError(
                    "live service must not run"
                ),
                create=True,
            ),
            patch("shutil.which", return_value=None),
            redirect_stdout(output),
        ):
            rc = main(["check"])

        self.assertEqual(rc, 0)
        self.assertIn(
            "Belum diperiksa",
            output.getvalue(),
        )

    def test_check_live_runs_probe_once_and_prints_timestamp(self):
        service = FakeLiveService()
        output = io.StringIO()

        with (
            patch(
                "xp.cli._build_live_check_service",
                return_value=service,
                create=True,
            ),
            patch("shutil.which", return_value=None),
            redirect_stdout(output),
        ):
            rc = main(["check", "--live"])

        rendered = output.getvalue()

        self.assertEqual(rc, 0)
        self.assertEqual(service.calls, 1)
        self.assertIn("LIVE", rendered)
        self.assertIn("Tersedia", rendered)
        self.assertIn(
            FIXED.isoformat(),
            rendered,
        )

    def test_not_checked_is_rendered_as_belum_diperiksa(self):
        from xp.readiness import capability_state_label

        label = capability_state_label(
            CapabilityState.NOT_CHECKED
        )

        self.assertEqual(
            label,
            "Belum diperiksa",
        )
        self.assertNotEqual(
            label,
            "Tersedia",
        )


class AF03ProvenanceCLITests(unittest.TestCase):
    def test_live_and_ai_knowledge_have_distinct_labels(self):
        from xp.cli import _provenance_mode_label

        live = Provenance(
            source="web",
            processor=None,
            via="web-search",
            live=True,
        )

        ai = Provenance(
            source="ai-knowledge",
            processor="provider-model",
            via="ai-gateway",
            live=False,
        )

        self.assertEqual(
            _provenance_mode_label(live),
            "LIVE",
        )
        self.assertEqual(
            _provenance_mode_label(ai),
            "AI KNOWLEDGE",
        )


class AF03ActivityCLITests(unittest.TestCase):
    def test_activity_reads_completed_job_from_persistent_history(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)

            writer = ActivityStore.for_home(home)
            writer.append(
                ActivityEvent(
                    event_id="evt-1",
                    job_id="completed-job-1",
                    timestamp=FIXED,
                    category=ActivityCategory.AI,
                    action="AI completion",
                    provenance=Provenance(
                        source="ai-knowledge",
                        processor="actual-model",
                        via="openai-compatible",
                        live=False,
                    ),
                    status=ActivityStatus.COMPLETED,
                    result_summary=(
                        "AI execution completed"
                    ),
                    metadata={
                        "source_count": 4,
                    },
                )
            )

            # CLI creates a fresh ActivityStore internally.
            output = io.StringIO()

            with (
                patch(
                    "xp.cli._home",
                    return_value=home,
                ),
                redirect_stdout(output),
            ):
                rc = main(
                    [
                        "activity",
                        "completed-job-1",
                    ]
                )

            rendered = output.getvalue()

            self.assertEqual(rc, 0)
            self.assertIn(
                "completed-job-1",
                rendered,
            )
            self.assertIn("Selesai", rendered)
            self.assertIn(
                "AI KNOWLEDGE",
                rendered,
            )
            self.assertIn(
                "ai-knowledge",
                rendered,
            )
            self.assertIn(
                "actual-model",
                rendered,
            )
            self.assertIn(
                "openai-compatible",
                rendered,
            )

    def test_unknown_activity_job_is_explicit_non_success(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            output = io.StringIO()

            with (
                patch(
                    "xp.cli._home",
                    return_value=home,
                ),
                redirect_stdout(output),
            ):
                rc = main(
                    [
                        "activity",
                        "missing-job",
                    ]
                )

            rendered = output.getvalue().lower()

            self.assertNotEqual(rc, 0)
            self.assertIn(
                "tidak ditemukan",
                rendered,
            )


if __name__ == "__main__":
    unittest.main()
