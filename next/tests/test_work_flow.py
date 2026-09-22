from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from xp_next.project_service import ProjectService
from xp_next.runtime import XPRuntime
from xp_next.work_flow import (
    WorkFlowNeedsAttention,
    discover_project_verifier,
    prepare_work,
)


class WorkFlowPreparationTests(unittest.TestCase):
    def _git_project(self, root: Path) -> None:
        import subprocess
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Fixture"], check=True)
        (root / "app.txt").write_text("SAFE\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "baseline"], check=True)

    def test_discovers_canonical_npm_verify_without_running_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                json.dumps({"scripts": {"verify": "node verify.mjs"}}),
                encoding="utf-8",
            )
            spec = discover_project_verifier(root)
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.name, "npm-verify")
        self.assertEqual(spec.argv, ("npm", "run", "verify"))

    def test_prepare_uses_active_git_project_and_human_goal(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            project = base / "project"
            project.mkdir()
            self._git_project(project)
            (project / "package.json").write_text(
                json.dumps({"scripts": {"verify": "node verify.mjs"}}),
                encoding="utf-8",
            )
            subprocess = __import__("subprocess")
            subprocess.run(["git", "-C", str(project), "add", "package.json"], check=True)
            subprocess.run(["git", "-C", str(project), "commit", "-qm", "add verifier"], check=True)

            with XPRuntime.open(home) as runtime:
                projects = ProjectService(runtime.store)
                projects.register("p1", "Project One", project, source_kind="git")
                projects.switch("p1")
                prepared = prepare_work(
                    projects,
                    goal="Perbaiki bug tanpa menyentuh production.",
                )

        self.assertEqual(prepared.project_id, "p1")
        self.assertEqual(prepared.project_name, "Project One")
        self.assertEqual(prepared.worker_prompt, "Perbaiki bug tanpa menyentuh production.")
        self.assertEqual(prepared.verifier.argv, ("npm", "run", "verify"))
        self.assertEqual(prepared.source_head and len(prepared.source_head), 40)

    def test_prepare_fails_closed_when_git_project_is_dirty(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            project = base / "project"
            project.mkdir()
            self._git_project(project)
            (project / "app.txt").write_text("DIRTY\n", encoding="utf-8")

            with XPRuntime.open(home) as runtime:
                projects = ProjectService(runtime.store)
                projects.register("p1", "Project One", project, source_kind="git")
                projects.switch("p1")
                with self.assertRaisesRegex(WorkFlowNeedsAttention, "clean"):
                    prepare_work(
                        projects,
                        goal="Perbaiki bug",
                        verifier_command="python -c 'print(1)'",
                    )

    def test_prepare_requires_a_safe_verifier_when_none_can_be_discovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            project = base / "project"
            project.mkdir()
            self._git_project(project)

            with XPRuntime.open(home) as runtime:
                projects = ProjectService(runtime.store)
                projects.register("p1", "Project One", project, source_kind="git")
                projects.switch("p1")
                with self.assertRaisesRegex(WorkFlowNeedsAttention, "verifier"):
                    prepare_work(projects, goal="Perbaiki bug")


if __name__ == "__main__":
    unittest.main()
