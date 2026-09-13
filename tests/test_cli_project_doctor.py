from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from xp.cli import main


class ProjectDoctorCLITests(unittest.TestCase):
    def test_project_audit_path_outputs_json(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            out = io.StringIO()
            with redirect_stdout(out):
                rc = main(["project", "audit", str(repo)])
            self.assertEqual(rc, 0)
            data = json.loads(out.getvalue())
            self.assertEqual(data["status"], "UNPROFILED")
            self.assertEqual(Path(data["repo_path"]), repo.resolve())


if __name__ == "__main__":
    unittest.main()
