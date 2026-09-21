from __future__ import annotations
import sqlite3
from pathlib import Path
import tempfile
import unittest
from xp_next import __version__
from xp_next.job_state import JobState, can_transition
from xp_next.state_schema import SCHEMA_VERSION, initialize_schema, table_names
from xp_next.service import doctor, status

class XPNextContractTests(unittest.TestCase):
    def test_version_is_explicit_dev_version(self):
        self.assertEqual(__version__, "0.1.0.dev0")

    def test_job_state_contract_is_complete(self):
        expected = {
            "DRAFT", "PLANNING", "READY", "AWAITING_APPROVAL", "RUNNING",
            "VERIFYING", "READY_TO_REVIEW", "APPLYING", "VERIFYING_APPLIED",
            "COMPLETED", "NEEDS_ATTENTION", "ROLLED_BACK", "CANCELLED",
        }
        self.assertEqual({state.value for state in JobState}, expected)

    def test_terminal_states_do_not_transition(self):
        for state in (JobState.COMPLETED, JobState.ROLLED_BACK, JobState.CANCELLED):
            self.assertFalse(can_transition(state, JobState.RUNNING))

    def test_primary_happy_path_transitions_are_explicit(self):
        path = [
            JobState.DRAFT, JobState.PLANNING, JobState.READY,
            JobState.AWAITING_APPROVAL, JobState.RUNNING, JobState.VERIFYING,
            JobState.READY_TO_REVIEW, JobState.APPLYING,
            JobState.VERIFYING_APPLIED, JobState.COMPLETED,
        ]
        for current, target in zip(path, path[1:]):
            self.assertTrue(can_transition(current, target))

    def test_schema_v1_creates_canonical_tables(self):
        conn = sqlite3.connect(":memory:")
        initialize_schema(conn)
        self.assertEqual(SCHEMA_VERSION, 1)
        self.assertEqual(
            table_names(conn),
            {
                "meta", "projects", "jobs", "job_steps", "approvals",
                "activities", "recovery_points", "artifacts", "devices",
                "preferences", "automations",
            },
        )
        row = conn.execute("select value from meta where key='schema_version'").fetchone()
        self.assertEqual(row[0], "1")

    def test_status_is_honest_about_local_state_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = status(Path(tmp) / "xp-home")
        self.assertEqual(snapshot["product"], "XP Next")
        self.assertEqual(snapshot["phase"], "CP-08F")
        self.assertEqual(snapshot["runtime"], "LOCAL_STATE_ACTIVE")
        self.assertEqual(snapshot["ai"], "LOCAL_READ_ONLY_ADAPTER")
        self.assertEqual(snapshot["worker"], "LOCAL_HERMES_ISOLATED_ADAPTER")
        self.assertFalse(snapshot["network_required"])

    def test_doctor_is_local_only(self):
        report = doctor()
        self.assertIn(report["python"], {"READY", "UNAVAILABLE"})
        self.assertIn(report["sqlite"], {"READY", "UNAVAILABLE"})
        self.assertIn(report["git"], {"READY", "UNAVAILABLE"})
        self.assertFalse(report["network_probe_performed"])

if __name__ == "__main__":
    unittest.main()
