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


class XPPlusCompatibilityReaderTests(unittest.TestCase):
    def _snapshot(self, root):
        return {
            p.relative_to(root).as_posix(): (
                p.read_bytes(),
                p.stat().st_mtime_ns,
                p.stat().st_size,
            )
            for p in root.rglob("*")
            if p.is_file()
        }

    def test_state_version_constant_remains_one(self):
        from xp.models import STATE_VERSION
        self.assertEqual(STATE_VERSION, 1)

    def test_fixture_audit_is_strictly_read_only_hash_mtime_size(self):
        from xp.compatibility import CompatibilityAudit

        root = Path("tests/fixtures")
        before = self._snapshot(root)
        report = CompatibilityAudit(Path.home()).run(root)
        after = self._snapshot(root)

        self.assertEqual(report.status, "CLEAR", report.to_dict())
        self.assertTrue(report.read_only)
        self.assertEqual(before, after)

        codes = {
            item.code for item in report.checks
            if item.status == "CLEAR"
        }
        for code in (
            "PROFILE_V1",
            "STATE_V1",
            "CHECKPOINT_V1",
            "PACKAGE_PROTOCOL_V1",
            "REGISTRY_V1",
            "CONTROL_STATE_V1",
            "INCIDENT_ZIP_V1",
        ):
            self.assertIn(code, codes)

    def test_locked_remote_state_and_checkpoint_remain_readable(self):
        from xp.checkpoint import read_checkpoint_state_v1
        from xp.models import read_run_state_v1

        state = read_run_state_v1(
            Path("tests/fixtures/state_v1/locked_remote.json")
        )
        checkpoint = read_checkpoint_state_v1(
            Path(
                "tests/fixtures/checkpoint_v1/"
                "CHECKPOINT_STATE.json"
            )
        )
        self.assertEqual(state.state_version, 1)
        self.assertEqual(state.stage, "LOCKED_REMOTE")
        self.assertEqual(checkpoint.stage, "LOCKED_REMOTE")

    def test_protocol_v1_manifest_reader_accepts_frozen_fixture(self):
        from xp.packages import read_package_manifest_v1

        manifest = read_package_manifest_v1(
            Path("tests/fixtures/package_v1/manifest.json")
        )
        self.assertEqual(manifest.protocol_version, 1)

    def test_profile_and_registry_v1_allow_additive_fields(self):
        import json
        import tempfile
        from xp.project_registry import (
            read_project_profile_v1,
            read_registry_v1,
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            profile_path = root / "project.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "profile_version": 1,
                        "project_id": "additive",
                        "name": "Additive",
                        "runtimes": [],
                        "metadata": {},
                        "future_optional_field": {"safe": True},
                    }
                ),
                encoding="utf-8",
            )
            registry_path = root / "registry.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "projects": {
                            "additive": {
                                "project_id": "additive",
                                "name": "Additive",
                                "repo_path": None,
                                "last_active_at": None,
                                "status": "REMOTE_ONLY",
                                "remote_url": None,
                                "future_optional_field": "ok",
                            }
                        },
                        "last_active": "additive",
                        "future_optional_field": "ok",
                    }
                ),
                encoding="utf-8",
            )

            profile = read_project_profile_v1(profile_path)
            registry = read_registry_v1(registry_path)

        self.assertEqual(profile.profile_version, 1)
        self.assertEqual(registry["version"], 1)

    def test_incident_and_remediation_fixture_preserves_protocol_v1_binding(self):
        from xp.compatibility import read_incident_handoff_v1
        from xp.packages import RunContext, inspect_package, validate_package

        incident = read_incident_handoff_v1(
            Path(
                "tests/fixtures/incident_v1/"
                "XP_GPT_INCIDENT_fixture-next_"
                "fixture-next-CS-05-P1-fixture.zip"
            )
        )
        manifest = inspect_package(
            Path(
                "tests/fixtures/remediation_v1/"
                "XP_PKG_REMEDIATION_fixture-next_CS-05-P1.zip"
            )
        )

        self.assertEqual(manifest.protocol_version, 1)
        self.assertEqual(manifest.package_type, "REMEDIATION")
        self.assertEqual(manifest.run_id, incident.run_id)
        self.assertEqual(manifest.incident_id, incident.incident_id)
        self.assertEqual(
            manifest.incident_challenge,
            incident.incident_challenge,
        )

        context = RunContext(
            project_id=incident.project_id,
            stage=incident.stage,
            base_fingerprint=manifest.base_fingerprint,
            run_id=incident.run_id,
            incident_id=incident.incident_id,
            incident_challenge=incident.incident_challenge,
        )
        report = validate_package(manifest, context)
        self.assertEqual(report.status, "CLEAR", report.reasons)

    def test_schema_and_pkgbuild_operation_sets_agree(self):
        from xp.pkgbuild import _FILE_OPS, _SQL_OPS
        from xp.schema import SPEC_OPERATION_TYPES

        executable = (
            set(_FILE_OPS)
            | set(_SQL_OPS)
            | {"DELETE_ALLOWED_FILE", "APPLY_PATCH"}
        )
        self.assertEqual(set(SPEC_OPERATION_TYPES), executable)
