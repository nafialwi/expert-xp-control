from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from xp.activity import (
    ActivityCategory,
    ActivityEvent,
    ActivityStatus,
    ActivityStore,
    ActivityStoreError,
    Provenance,
)


FIXED = datetime(2026, 9, 17, 13, 0, tzinfo=timezone.utc)


def event(
    *,
    event_id: str,
    job_id: str = "AF03-JOB-001",
    status: ActivityStatus = ActivityStatus.COMPLETED,
    metadata=None,
):
    return ActivityEvent(
        event_id=event_id,
        job_id=job_id,
        timestamp=FIXED,
        category=ActivityCategory.TOOL,
        action="Run observable operation",
        provenance=Provenance(
            source="project-local",
            processor="Gemini",
            via="test-runner",
            live=False,
        ),
        status=status,
        result_summary="observable result",
        metadata={} if metadata is None else metadata,
    )


class ActivityModelTests(unittest.TestCase):
    def test_source_processor_and_via_are_independent(self):
        provenance = Provenance(
            source="github",
            processor="Gemini",
            via="github-tool",
            live=True,
        )

        self.assertEqual(provenance.source, "github")
        self.assertEqual(provenance.processor, "Gemini")
        self.assertEqual(provenance.via, "github-tool")
        self.assertTrue(provenance.live)

    def test_started_failed_and_completed_are_distinct(self):
        self.assertIsNot(
            ActivityStatus.STARTED,
            ActivityStatus.COMPLETED,
        )
        self.assertIsNot(
            ActivityStatus.FAILED,
            ActivityStatus.COMPLETED,
        )
        self.assertIsNot(
            ActivityStatus.NEEDS_ATTENTION,
            ActivityStatus.COMPLETED,
        )

    def test_event_is_immutable(self):
        item = event(event_id="evt-immutable")

        with self.assertRaises(Exception):
            item.status = ActivityStatus.FAILED


class ActivityStoreTests(unittest.TestCase):
    def test_activity_history_survives_fresh_store_instance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "activity"

            first = ActivityStore(root)

            first.append(
                event(
                    event_id="evt-1",
                    status=ActivityStatus.STARTED,
                )
            )
            first.append(
                event(
                    event_id="evt-2",
                    status=ActivityStatus.COMPLETED,
                )
            )
            first.append(
                event(
                    event_id="evt-3",
                    status=ActivityStatus.NEEDS_ATTENTION,
                )
            )

            second = ActivityStore(root)
            history = second.list_for_job("AF03-JOB-001")

            self.assertEqual(
                tuple(item.event_id for item in history),
                ("evt-1", "evt-2", "evt-3"),
            )
            self.assertEqual(
                tuple(item.status for item in history),
                (
                    ActivityStatus.STARTED,
                    ActivityStatus.COMPLETED,
                    ActivityStatus.NEEDS_ATTENTION,
                ),
            )

    def test_secret_and_hidden_reasoning_values_are_not_persisted(self):
        secret_values = (
            "BEARER-SECRET-123",
            "API-SECRET-456",
            "TOKEN-SECRET-789",
            "PASSWORD-SECRET-ABC",
            "COT-SECRET-DEF",
            "SCRATCHPAD-SECRET-GHI",
            "REASONING-SECRET-JKL",
        )

        metadata = {
            "authorization": secret_values[0],
            "api_key": secret_values[1],
            "token": secret_values[2],
            "password": secret_values[3],
            "chain_of_thought": secret_values[4],
            "scratchpad": secret_values[5],
            "reasoning_content": secret_values[6],
            "safe": {
                "source_count": 4,
                "Authorization": "NESTED-SECRET",
            },
        }

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "activity"
            store = ActivityStore(root)

            store.append(
                event(
                    event_id="evt-secret",
                    metadata=metadata,
                )
            )

            serialized = "\n".join(
                p.read_text(encoding="utf-8")
                for p in root.glob("*.jsonl")
            )

            for value in secret_values:
                self.assertNotIn(value, serialized)

            self.assertNotIn("NESTED-SECRET", serialized)

            restored = store.list_for_job(
                "AF03-JOB-001"
            )[0]

            self.assertEqual(
                restored.metadata["safe"]["source_count"],
                4,
            )

            self.assertNotIn(
                "chain_of_thought",
                restored.metadata,
            )
            self.assertNotIn(
                "scratchpad",
                restored.metadata,
            )
            self.assertNotIn(
                "reasoning_content",
                restored.metadata,
            )

    def test_job_id_cannot_escape_activity_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "activity"
            store = ActivityStore(root)

            store.append(
                event(
                    event_id="evt-path",
                    job_id="../../outside",
                )
            )

            files = tuple(root.glob("*.jsonl"))

            self.assertEqual(len(files), 1)
            self.assertEqual(
                store.list_for_job("../../outside")[0].event_id,
                "evt-path",
            )

            self.assertFalse(
                (Path(td) / "outside.jsonl").exists()
            )

    def test_malformed_record_is_explicit_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "activity"
            store = ActivityStore(root)

            store.append(event(event_id="evt-ok"))

            target = next(root.glob("*.jsonl"))

            with target.open(
                "a",
                encoding="utf-8",
            ) as handle:
                handle.write("{broken json}\n")

            with self.assertRaises(ActivityStoreError):
                store.list_for_job("AF03-JOB-001")


    def test_activity_store_for_home_uses_engine_owned_activity_path(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)

            store = ActivityStore.for_home(home)

            self.assertEqual(
                store.root,
                home.resolve()
                / ".expert-workstation"
                / "activity",
            )

    def test_xp_paths_exposes_activity_directory_and_runtime_setup_creates_it(self):
        from xp.paths import XPPaths

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            paths = XPPaths.from_home(home)

            self.assertEqual(
                paths.activity,
                home.resolve()
                / ".expert-workstation"
                / "activity",
            )

            self.assertFalse(paths.activity.exists())

            paths.ensure_runtime_dirs()

            self.assertTrue(paths.activity.is_dir())



if __name__ == "__main__":
    unittest.main()


class ActivityObjectiveMetadataTests(unittest.TestCase):
    def test_test_result_metadata_round_trips_exact_counts(self):
        from xp.activity import test_result_metadata

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "activity"
            store = ActivityStore(root)

            event = ActivityEvent(
                event_id="task6-test-counts",
                job_id="task6-job",
                timestamp=datetime(
                    2026, 9, 17, 15, 0,
                    tzinfo=timezone.utc,
                ),
                category=ActivityCategory.TEST,
                action="Run verification tests",
                provenance=Provenance(
                    source="test-runner",
                    processor=None,
                    via="unittest",
                    live=False,
                ),
                status=ActivityStatus.COMPLETED,
                result_summary="Verification completed",
                metadata=test_result_metadata(
                    passed=38,
                    failed=0,
                    skipped=1,
                ),
            )

            store.append(event)

            restored = ActivityStore(root).list_for_job(
                "task6-job"
            )

            self.assertEqual(len(restored), 1)
            self.assertEqual(
                restored[0].metadata,
                {
                    "passed": 38,
                    "failed": 0,
                    "skipped": 1,
                },
            )

    def test_source_result_metadata_round_trips_source_count(self):
        from xp.activity import source_result_metadata

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "activity"
            store = ActivityStore(root)

            event = ActivityEvent(
                event_id="task6-source-count",
                job_id="task6-source-job",
                timestamp=datetime(
                    2026, 9, 17, 15, 1,
                    tzinfo=timezone.utc,
                ),
                category=ActivityCategory.LIVE_WEB,
                action="Read sources",
                provenance=Provenance(
                    source="web",
                    processor=None,
                    via="search",
                    live=True,
                ),
                status=ActivityStatus.COMPLETED,
                result_summary="Sources read",
                metadata=source_result_metadata(
                    source_count=4
                ),
            )

            store.append(event)

            restored = ActivityStore(root).list_for_job(
                "task6-source-job"
            )

            self.assertEqual(len(restored), 1)
            self.assertEqual(
                restored[0].metadata,
                {"source_count": 4},
            )

    def test_objective_metadata_rejects_negative_counts(self):
        from xp.activity import (
            source_result_metadata,
            test_result_metadata,
        )

        with self.assertRaises(ValueError):
            test_result_metadata(
                passed=-1,
                failed=0,
                skipped=0,
            )

        with self.assertRaises(ValueError):
            source_result_metadata(
                source_count=-1
            )
