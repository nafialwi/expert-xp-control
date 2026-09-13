from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from xp.bundle import BundleBuilder
from xp.compatibility import CompatibilityAudit
from xp.engine_lifecycle import EngineCandidate, EngineLifecycle
from xp.project_doctor import ProjectAudit, ProjectDoctor
from xp.schema import schema_for, validate_spec_dict


ROOT = Path(__file__).resolve().parents[1]


def _project(root: Path) -> Path:
    repo = root / "project"
    repo.mkdir()
    (repo / ".git").mkdir()
    xp = repo / ".xp"
    xp.mkdir()
    (xp / "project.json").write_text(
        json.dumps(
            {
                "profile_version": 1,
                "project_id": "interface-fixture",
                "name": "Interface Fixture",
                "runtimes": ["python"],
                "source_adapter": "git",
                "database_adapter": None,
                "verify_adapter": "unittest",
                "deployment_adapter": None,
                "metadata": {},
            }
        ),
        encoding="utf-8",
    )
    (xp / "policies.json").write_text(
        json.dumps(
            {
                "source_verify": [{"adapter": "python", "command": "python -m unittest"}],
                "protected_branches": ["main"],
                "allowed_branch_prefixes": ["work/"],
            }
        ),
        encoding="utf-8",
    )
    (xp / "compatibility.json").write_text("{}\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0'\n", encoding="utf-8")
    return repo


class XP10InterfaceContractTests(unittest.TestCase):
    def test_locked_plan_public_interfaces_are_callable_and_exercised_without_mocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = _project(root)
            home = root / "home"
            home.mkdir()

            candidate = EngineCandidate("2.1.0", ROOT, "INSTALLED")
            self.assertEqual(candidate.version, "2.1.0")
            lifecycle = EngineLifecycle(home)
            for name in (
                "install_candidate",
                "activate_candidate",
                "rollback_to_previous",
                "health_check",
            ):
                self.assertTrue(callable(getattr(lifecycle, name)))

            for kind in ("work", "remediation", "project-profile"):
                self.assertIsInstance(schema_for(kind), dict)
            self.assertEqual(
                validate_spec_dict(
                    {
                        "spec_version": "1.0",
                        "package_type": "WORK",
                        "project_id": "interface-fixture",
                        "allowed_paths": ["src"],
                        "operations": [],
                        "human_qa": [],
                    }
                ),
                [],
            )

            audit = ProjectDoctor(home).inspect(repo)
            self.assertIsInstance(audit, ProjectAudit)
            self.assertIn(
                audit.status,
                {"UNPROFILED", "PROFILE_INCOMPLETE", "WORK_READY", "RECOVERY_REQUIRED"},
            )
            self.assertIsInstance(audit.findings, tuple)

            engine = root / "engine-source"
            engine.mkdir()
            (engine / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            builder = BundleBuilder(home, engine_root=engine)
            compact = builder.compact(repo)
            deep = builder.deep(repo)
            self.assertIsInstance(compact, str)
            self.assertIsInstance(deep, str)
            self.assertNotIn("##### FILE: module.py #####", compact)
            self.assertIn("##### FILE: module.py #####", deep)

            report = CompatibilityAudit(home).run(ROOT / "tests" / "fixtures")
            self.assertEqual(report.status, "CLEAR", report.to_dict())
            self.assertTrue(report.read_only)


if __name__ == "__main__":
    unittest.main()
