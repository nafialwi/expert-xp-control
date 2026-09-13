from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from xp.project_context import ProjectSessionResolver
from xp.project_registry import ProjectProfile, ProjectRegistry


def _git(repo: Path):
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)


def _make_project(root: Path, project_id: str) -> Path:
    repo = root / project_id
    repo.mkdir()
    _git(repo)
    xp = repo / ".xp"
    xp.mkdir()
    (xp / "project.json").write_text(
        json.dumps(
            {
                "profile_version": 1,
                "project_id": project_id,
                "name": project_id,
                "runtimes": ["node"],
                "source_adapter": "git",
                "database_adapter": None,
                "verify_adapter": "npm-script",
                "deployment_adapter": None,
                "metadata": {},
            }
        ),
        encoding="utf-8",
    )
    return repo


class ProjectSessionResolverTests(unittest.TestCase):
    def test_nested_cwd_selects_registered_project_without_mutating_last_active(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            alpha = _make_project(root, "alpha")
            beta = _make_project(root, "beta")
            nested = beta / "src" / "feature"
            nested.mkdir(parents=True)

            registry = ProjectRegistry.for_home(home)
            registry.register(ProjectProfile("alpha", "alpha", runtimes=("node",)), alpha)
            registry.register(ProjectProfile("beta", "beta", runtimes=("node",)), beta)
            registry.activate("alpha")
            before = registry.path.read_bytes()

            selection = ProjectSessionResolver(home).resolve(nested)

            self.assertEqual(selection.source, "cwd")
            self.assertEqual(selection.project.project_id, "beta")
            self.assertEqual(registry.path.read_bytes(), before)
            self.assertEqual(registry.last_active().project_id, "alpha")

    def test_repo_without_xp_falls_back_to_explicitly_switched_last_active(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            alpha = _make_project(root, "alpha")
            plain = root / "plain"
            plain.mkdir()
            _git(plain)

            registry = ProjectRegistry.for_home(home)
            registry.register(ProjectProfile("alpha", "alpha", runtimes=("node",)), alpha)
            registry.activate("alpha")

            selection = ProjectSessionResolver(home).resolve(plain)

            self.assertEqual(selection.source, "last_active")
            self.assertEqual(selection.project.project_id, "alpha")

    def test_unregistered_profile_does_not_silently_become_active(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            alpha = _make_project(root, "alpha")
            rogue = _make_project(root, "rogue")

            registry = ProjectRegistry.for_home(home)
            registry.register(ProjectProfile("alpha", "alpha", runtimes=("node",)), alpha)

            selection = ProjectSessionResolver(home).resolve(rogue)

            self.assertEqual(selection.source, "last_active")
            self.assertEqual(selection.project.project_id, "alpha")

    def test_no_cwd_project_and_no_last_active_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            plain = root / "plain"
            plain.mkdir()

            selection = ProjectSessionResolver(home).resolve(plain)

            self.assertEqual(selection.source, "none")
            self.assertIsNone(selection.project)


if __name__ == "__main__":
    unittest.main()
