from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from xp.models import RunState
from xp.packages import RunContext, inspect_package, validate_package
from xp.project_registry import ProjectProfile

FIXTURES = Path(__file__).parent / "fixtures"

class BackwardCompatibilityTests(unittest.TestCase):
    def test_profile_v1_remains_readable(self):
        data=json.loads((FIXTURES/"profile_v1"/"project.json").read_text())
        profile=ProjectProfile.from_dict(data)
        self.assertEqual(profile.profile_version,1)
        self.assertEqual(profile.project_id,"fixture-project")
        self.assertEqual(profile.runtimes,("node","python"))
        self.assertEqual(profile.source_adapter,"git")
        self.assertEqual(profile.database_adapter,"postgresql")
        self.assertEqual(profile.verify_adapter,"npm-script")

    def test_state_v1_locked_remote_remains_readable(self):
        data=json.loads((FIXTURES/"state_v1"/"locked_remote.json").read_text())
        state=RunState.from_dict(data)
        self.assertEqual(state.state_version,1)
        self.assertEqual(state.stage,"LOCKED_REMOTE")
        self.assertEqual(state.metadata["remote_lease"],"RELEASED")

    def test_checkpoint_v1_shape_remains_readable_without_migration(self):
        data=json.loads((FIXTURES/"checkpoint_v1"/"CHECKPOINT_STATE.json").read_text())
        self.assertEqual(data["stage"],"LOCKED_REMOTE")
        self.assertEqual(data["source_archive"],"SOURCE.zip")
        self.assertEqual(data["evidence"]["source_verification"],"CLEAR")
        self.assertEqual(data["evidence"]["human_qa"]["status"],"CLEAR")

    def test_protocol_v1_manifest_uses_current_operation_and_human_qa_keys(self):
        fixture=FIXTURES/"package_v1"/"manifest.json"
        data=json.loads(fixture.read_text())
        with tempfile.TemporaryDirectory() as td:
            package=Path(td)/"package.zip"
            with zipfile.ZipFile(package,"w") as zf: zf.writestr("manifest.json",json.dumps(data))
            manifest=inspect_package(package)
        self.assertEqual(manifest.protocol_version,1)
        self.assertEqual(manifest.operations[0]["type"],"DELETE_ALLOWED_FILE")
        self.assertEqual(manifest.human_qa,("Fixture QA remains explicit.",))
        report=validate_package(manifest,RunContext(project_id="fixture-project",stage="IDLE",base_fingerprint="fixture-fingerprint"))
        self.assertEqual(report.status,"CLEAR",report.reasons)

    def test_legacy_empty_verify_and_next_configured_verify_are_frozen_as_distinct_inputs(self):
        legacy=json.loads((FIXTURES/"profile_v1"/"policies-legacy-incomplete.json").read_text())
        nxt=json.loads((FIXTURES/"profile_v1"/"policies-next.json").read_text())
        self.assertEqual(legacy["source_verify"],[])
        self.assertEqual(nxt["source_verify"],[{"adapter":"node","script":"verify"}])

if __name__ == "__main__": unittest.main()
