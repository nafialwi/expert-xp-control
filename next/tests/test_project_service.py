from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from xp_next.project_service import ProjectRootError, ProjectService
from xp_next.runtime import XPRuntime
from xp_next.service import status


class ProjectServiceTests(unittest.TestCase):
    def test_register_list_switch_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "xp-home"
            p1 = base / "project-one"
            p2 = base / "project-two"
            p1.mkdir()
            p2.mkdir()

            with XPRuntime.open(home) as runtime:
                service = ProjectService(runtime.store)
                service.register("p1", "Project One", p1, source_kind="local")
                service.register("p2", "Project Two", p2, source_kind="local")
                service.switch("p2")
                self.assertEqual(
                    [item["id"] for item in service.list_projects()],
                    ["p1", "p2"],
                )
                self.assertEqual(service.current()["id"], "p2")

            with XPRuntime.open(home) as runtime:
                service = ProjectService(runtime.store)
                self.assertEqual(service.current()["id"], "p2")
                self.assertEqual(len(service.list_projects()), 2)

    def test_missing_project_root_fails_before_database_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "xp-home"
            with XPRuntime.open(home) as runtime:
                service = ProjectService(runtime.store)
                with self.assertRaises(ProjectRootError):
                    service.register(
                        "missing",
                        "Missing",
                        base / "does-not-exist",
                        source_kind="local",
                    )
                self.assertEqual(service.list_projects(), [])

    def test_registered_root_is_absolute_resolved_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "xp-home"
            project = base / "project"
            project.mkdir()
            with XPRuntime.open(home) as runtime:
                service = ProjectService(runtime.store)
                row = service.register("p1", "One", project, source_kind="local")
                self.assertEqual(row["root_path"], str(project.resolve()))

    def test_state_backed_status_reports_project_count_and_active_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "xp-home"
            project = base / "project"
            project.mkdir()
            with XPRuntime.open(home) as runtime:
                service = ProjectService(runtime.store)
                service.register("p1", "One", project, source_kind="local")
                service.switch("p1")
            snapshot = status(home)
            self.assertEqual(snapshot["phase"], "CP-08C")
            self.assertEqual(snapshot["runtime"], "LOCAL_STATE_ACTIVE")
            self.assertEqual(snapshot["database"], "READY")
            self.assertEqual(snapshot["project_count"], 1)
            self.assertEqual(snapshot["active_project"]["id"], "p1")
            self.assertEqual(
                snapshot["active_project_inspection"]["project_id"],
                "p1",
            )
            self.assertEqual(
                set(snapshot["local_capabilities"]),
                {"python", "git", "node", "sqlite", "local_qwen", "hermes"},
            )
            self.assertFalse(snapshot["network_probe_performed"])
            self.assertEqual(snapshot["ai"], "LOCAL_READ_ONLY_ADAPTER")
            self.assertEqual(snapshot["worker"], "LOCAL_HERMES_ISOLATED_ADAPTER")
            self.assertFalse(snapshot["network_required"])


if __name__ == "__main__":
    unittest.main()
