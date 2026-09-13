from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from xp.cli import _session_project
from xp.project_registry import ProjectProfile, ProjectRegistry


class CwdAwareCLITests(unittest.TestCase):
    def test_cli_session_project_prefers_cwd_and_does_not_change_registry(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            alpha = root / "alpha"
            beta = root / "beta"
            for repo, project_id in ((alpha, "alpha"), (beta, "beta")):
                repo.mkdir()
                subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
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

            registry = ProjectRegistry.for_home(home)
            registry.register(ProjectProfile("alpha", "alpha", runtimes=("node",)), alpha)
            registry.register(ProjectProfile("beta", "beta", runtimes=("node",)), beta)
            registry.activate("alpha")
            before = registry.path.read_bytes()

            with patch.dict(os.environ, {"XP_USER_HOME": str(home)}):
                selected = _session_project(beta)

            self.assertEqual(selected.project_id, "beta")
            self.assertEqual(registry.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
