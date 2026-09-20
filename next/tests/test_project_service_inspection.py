from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from xp_next.project_service import ProjectService
from xp_next.runtime import XPRuntime


class ProjectServiceInspectionTests(unittest.TestCase):
    def test_inspect_registered_project_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "xp-home"
            project = base / "project"
            project.mkdir()
            package = project / "package.json"
            package.write_text("{}", encoding="utf-8")
            before = package.read_bytes()

            with XPRuntime.open(home) as runtime:
                service = ProjectService(runtime.store)
                service.register("p1", "One", project, source_kind="local")
                facts = service.inspect("p1")
                self.assertTrue(facts["markers"]["package_json"])
                self.assertEqual(package.read_bytes(), before)

    def test_inspect_current_project_when_id_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "xp-home"
            project = base / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text(
                "[project]\nname='fixture'\n",
                encoding="utf-8",
            )

            with XPRuntime.open(home) as runtime:
                service = ProjectService(runtime.store)
                service.register("p1", "One", project, source_kind="local")
                service.switch("p1")
                facts = service.inspect()
                self.assertEqual(facts["project_id"], "p1")
                self.assertIn("python", facts["stack_hints"])


if __name__ == "__main__":
    unittest.main()
