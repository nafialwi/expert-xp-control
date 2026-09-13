from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from xp.packages import RunContext, inspect_package, validate_package
from xp.schema import schema_for, validate_spec_dict, render_handshake_schema_section


class CanonicalSchemaTests(unittest.TestCase):
    def test_work_schema_names_current_fields(self):
        schema = schema_for("work")
        self.assertIn("operations", schema["required"])
        self.assertIn("allowed_paths", schema["required"])
        self.assertEqual(schema["operation_key"], "type")
        self.assertEqual(schema["human_qa_key"], "human_qa")
        self.assertIn("DELETE_ALLOWED_FILE", schema["operation_types"])

    def test_remediation_and_profile_are_exposed(self):
        self.assertEqual(schema_for("remediation")["package_type"], "REMEDIATION")
        profile = schema_for("project-profile")
        self.assertEqual(profile["profile_version"], 1)
        self.assertEqual(profile["required"], ["project_id", "name"])

    def test_historical_drift_aliases_are_rejected(self):
        spec = {
            "allowed_paths": ["src"],
            "operations": [{"op": "ADD_FILE", "path": "src/a.txt", "content": "x"}],
            "human_qa_checklist": ["check"],
        }
        errors = validate_spec_dict(spec)
        joined = "\n".join(errors)
        self.assertIn("human_qa_checklist", joined)
        self.assertIn("canonical operation key 'type'", joined)

    def test_scope_and_content_are_validated_before_build(self):
        errors = validate_spec_dict({
            "allowed_paths": ["src"],
            "operations": [
                {"type": "ADD_FILE", "path": "docs/outside.txt"},
                {"type": "UNKNOWN", "path": "src/a.txt"},
            ],
        })
        joined = "\n".join(errors)
        self.assertIn("outside allowed_paths", joined)
        self.assertIn("requires 'content'", joined)
        self.assertIn("unsupported operation 'UNKNOWN'", joined)

    def test_existing_protocol_v1_fixture_manifest_still_validates(self):
        fixture = Path("tests/fixtures/package_v1/manifest.json")
        data = json.loads(fixture.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            package = Path(td) / "fixture.zip"
            with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("manifest.json", json.dumps(data))
            manifest = inspect_package(package)
            context = RunContext(
                project_id=manifest.project_id,
                stage=manifest.expected_state,
                base_fingerprint=manifest.base_fingerprint,
                run_id=manifest.run_id,
                incident_id=manifest.incident_id,
                incident_challenge=manifest.incident_challenge,
            )
            report = validate_package(manifest, context)
        self.assertEqual(report.status, "CLEAR", report.reasons)

    def test_handshake_schema_section_is_generated_from_schema(self):
        doc = Path("docs/handshake.md").read_text(encoding="utf-8")
        self.assertIn(render_handshake_schema_section().strip(), doc)
        self.assertNotIn("human_qa_checklist", doc)
