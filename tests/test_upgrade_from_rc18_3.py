from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from xp.cli import _upgrade_cmd


def _run(cmd, cwd):
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )


class UpgradeFromRC183Tests(unittest.TestCase):
    @staticmethod
    def _build_remote(root: Path, version: str) -> Path:
        remote = root / "remote.git"
        seed = root / "seed"
        seed.mkdir()

        _run(["git", "init"], seed)
        _run(["git", "checkout", "-b", "xp-engine"], seed)
        _run(["git", "config", "user.email", "xp-test@example.invalid"], seed)
        _run(["git", "config", "user.name", "XP Test"], seed)

        package = seed / "src" / "xp"
        tests = seed / "tests"
        package.mkdir(parents=True)
        tests.mkdir()
        (tests / "__init__.py").write_text("", encoding="utf-8")
        (package / "__init__.py").write_text(
            f'__version__ = "{version}"\n',
            encoding="utf-8",
        )
        (package / "cli.py").write_text(
            "from . import __version__\n"
            "import sys\n"
            "def main():\n"
            "    if sys.argv[1:] == ['version']:\n"
            "        print(f'Expert Workstation XP {__version__}')\n"
            "        return 0\n"
            "    if sys.argv[1:] == ['self-test']:\n"
            "        print('CORE: CLEAR')\n"
            "        return 0\n"
            "    return 2\n"
            "if __name__ == '__main__':\n"
            "    raise SystemExit(main())\n",
            encoding="utf-8",
        )
        (tests / "test_backward_compatibility.py").write_text(
            "import unittest\n"
            "class Compat(unittest.TestCase):\n"
            "    def test_v1(self): self.assertEqual(1, 1)\n",
            encoding="utf-8",
        )

        (package / "schema.py").write_text(
            "def schema_for(kind):\n"
            "    return {'schema_name': kind}\n",
            encoding="utf-8",
        )
        (package / "compatibility.py").write_text(
            "class Item:\n"
            "    def __init__(self, code, status): self.code=code; self.status=status\n"
            "class Report:\n"
            "    status='CLEAR'\n"
            "    read_only=True\n"
            "    checks=(Item('STATE_V1','CLEAR'), Item('REGISTRY_V1','CLEAR'), Item('READ_ONLY','CLEAR'))\n"
            "class CompatibilityAudit:\n"
            "    def __init__(self, home=None): self.home=home\n"
            "    def run(self, target): return Report()\n",
            encoding="utf-8",
        )

        _run(["git", "add", "."], seed)
        _run(["git", "commit", "-m", "candidate"], seed)
        _run(["git", "init", "--bare", str(remote)], root)
        _run(["git", "remote", "add", "origin", str(remote)], seed)
        _run(["git", "push", "-u", "origin", "xp-engine"], seed)
        return remote

    def test_upgrade_uses_archive_candidate_and_safe_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            xp_root = home / ".expert-workstation"
            xp_root.mkdir(parents=True)
            (xp_root / "active-version").write_text(
                "2.0.0-rc18.3\n",
                encoding="utf-8",
            )

            remote = self._build_remote(root, "2.1.0-rc1")
            engine = xp_root / "engine"
            _run(["git", "clone", "-b", "xp-engine", str(remote), str(engine)], root)
            before_head = _run(["git", "rev-parse", "HEAD"], engine).stdout.strip()

            with patch.dict(
                os.environ,
                {
                    "XP_USER_HOME": str(home),
                    "XP_ENGINE_BRANCH": "xp-engine",
                },
            ):
                rc = _upgrade_cmd()

            self.assertEqual(rc, 0)
            self.assertEqual(
                (xp_root / "previous-version").read_text().strip(),
                "2.0.0-rc18.3",
            )
            self.assertEqual(
                (xp_root / "active-version").read_text().strip(),
                "2.1.0-rc1",
            )
            self.assertTrue(
                (xp_root / "versions" / "2.1.0-rc1" / "src" / "xp" / "__init__.py").is_file()
            )

            after_head = _run(["git", "rev-parse", "HEAD"], engine).stdout.strip()
            self.assertEqual(after_head, before_head)
            self.assertEqual(
                _run(["git", "status", "--porcelain"], engine).stdout.strip(),
                "",
            )


if __name__ == "__main__":
    unittest.main()
