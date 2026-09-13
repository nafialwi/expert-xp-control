from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import xp
from xp.models import STATE_VERSION
from xp.project_registry import ProjectRegistry, load_project_profile
from xp.schema import PROTOCOL_VERSION, schema_for


ROOT = Path(__file__).resolve().parents[1]
HANDSHAKE = ROOT / "docs" / "handshake.md"
README = ROOT / "README.md"
CHANGELOG = ROOT / "CHANGELOG.md"
BEGIN = "<!-- XP_SCHEMA_CONTRACT_BEGIN -->"
END = "<!-- XP_SCHEMA_CONTRACT_END -->"


def _git(repo: Path, *args: str):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )


def _schema_block() -> dict:
    text = HANDSHAKE.read_text(encoding="utf-8")
    start = text.index(BEGIN) + len(BEGIN)
    end = text.index(END, start)
    payload = text[start:end].strip()
    return json.loads(payload)


class XP09StableIdentitySurfaceTests(unittest.TestCase):
    def test_stable_brand_and_version_keep_cli_name_xp(self):
        self.assertEqual(xp.__version__, "2.1.0")
        self.assertEqual(getattr(xp, "PRODUCT_NAME", None), "XP+")
        self.assertEqual(getattr(xp, "CLI_NAME", None), "xp")

    def test_ui_banner_displays_xp_plus(self):
        from xp.ui import header

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            header()
        rendered = out.getvalue()
        self.assertIn("XP+", rendered)
        self.assertIn("2.1.0", rendered)

    def test_cli_version_reports_xp_plus(self):
        result = subprocess.run(
            ["python", "-m", "xp.cli", "version"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            env={
                **__import__("os").environ,
                "PYTHONPATH": str(ROOT / "src"),
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("XP+", result.stdout)
        self.assertIn("2.1.0", result.stdout)

    def test_state_profile_protocol_versions_remain_v1(self):
        self.assertEqual(STATE_VERSION, 1)
        self.assertEqual(PROTOCOL_VERSION, 1)

        fixture = ROOT / "tests" / "fixtures" / "plain-git"
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "plain"
            shutil.copytree(fixture, repo)
            _git(repo, "init")
            _git(repo, "config", "user.email", "xp-rc@example.invalid")
            _git(repo, "config", "user.name", "XP RC")
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "fixture")

            profile = load_project_profile(repo)
            self.assertEqual(profile.profile_version, 1)

            home = Path(td) / "home"
            registry = ProjectRegistry.for_home(home)
            registry.register(profile, repo)
            registered = {
                item.project_id: item
                for item in registry.list_projects()
            }
            self.assertIn(profile.project_id, registered)
            self.assertEqual(
                registered[profile.project_id].project_id,
                profile.project_id,
            )
            self.assertTrue((repo / ".xp" / "project.json").is_file())
            self.assertFalse((repo / ".xp+").exists())

    def test_package_prefix_remains_xp_pkg(self):
        from xp.pkgbuild import build_package_from_spec

        fixture = ROOT / "tests" / "fixtures" / "plain-git"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "plain"
            shutil.copytree(fixture, repo)
            _git(repo, "init")
            _git(repo, "config", "user.email", "xp-rc@example.invalid")
            _git(repo, "config", "user.name", "XP RC")
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "fixture")

            profile = load_project_profile(repo)
            spec = root / "spec.json"
            spec.write_text(
                json.dumps(
                    {
                        "spec_version": "1.0",
                        "package_type": "WORK",
                        "project_id": profile.project_id,
                        "milestone": "XP08-IDENTITY",
                        "allowed_paths": ["probe.txt"],
                        "operations": [
                            {
                                "type": "ADD_FILE",
                                "path": "probe.txt",
                                "content": "identity\n",
                            }
                        ],
                        "human_qa": ["identity"],
                    }
                ),
                encoding="utf-8",
            )
            artifact = build_package_from_spec(
                root / "home",
                repo,
                spec,
            )
            self.assertTrue(
                artifact.name.startswith("XP_PKG_WORK_"),
                artifact.name,
            )

    def test_handshake_schema_block_is_generated_from_canonical_schema(self):
        block = _schema_block()
        expected = {
            name: schema_for(name)
            for name in (
                "work",
                "remediation",
                "project-profile",
            )
        }
        self.assertEqual(block, expected)

        work = block["work"]
        self.assertEqual(work["operation_key"], "type")
        self.assertEqual(work["human_qa_key"], "human_qa")

        rendered = json.dumps(block, sort_keys=True)
        self.assertNotIn("human_qa_checklist", rendered)
        self.assertNotIn('"operation_key": "op"', rendered)

    def test_release_docs_record_a_plus_and_generic_optional_contract(self):
        readme = README.read_text(encoding="utf-8")
        changelog = CHANGELOG.read_text(encoding="utf-8")

        for text in (readme, changelog):
            self.assertIn("Zone 1", text)
            self.assertIn("Zone 2", text)
            self.assertIn("Generic Toolchain Adapter", text)
            self.assertIn("optional-only", text)
            self.assertIn("XP+-09", text)

    def test_generic_toolchain_guard_regression_file_remains_present(self):
        guard = ROOT / "tests" / "test_generic_toolchain_qwen_guards.py"
        self.assertTrue(guard.is_file())


if __name__ == "__main__":
    unittest.main()
