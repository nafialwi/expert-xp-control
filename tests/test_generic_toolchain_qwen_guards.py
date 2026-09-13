from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from xp.adapters.base import AdapterError
from xp.adapters.generic import GenericToolchainAdapter
from xp.onboarding import SmartProjectOnboarder


class GenericToolchainQwenGuardTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "generic"
        repo.mkdir()
        subprocess.run(
            ["git", "init"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        tools = repo / "tools"
        tools.mkdir()
        script = tools / "verify.sh"
        script.write_text(
            "#!/bin/sh\nprintf 'ok\\n'\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        return repo

    @staticmethod
    def _decl(timeout=30):
        return {
            "verify": {
                "purpose": "verify",
                "argv": ["sh", "tools/verify.sh"],
                "cwd": ".",
                "timeout": timeout,
                "paths": ["tools/verify.sh"],
            }
        }

    def test_guard_shell_false_is_locked(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            adapter = GenericToolchainAdapter(repo, self._decl())
            fake = SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
            with patch(
                "xp.adapters.generic.subprocess.run",
                return_value=fake,
            ) as mocked:
                result = adapter.run("verify")

            self.assertEqual(result.returncode, 0)
            self.assertIs(mocked.call_args.kwargs["shell"], False)

    def test_guard_timeout_bounds_are_locked(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            for bad in (0, 3601):
                with self.subTest(timeout=bad):
                    with self.assertRaisesRegex(AdapterError, "timeout"):
                        GenericToolchainAdapter(
                            repo,
                            self._decl(timeout=bad),
                        )

    def test_optional_only_onboarding_never_auto_selects_generic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "static"
            repo.mkdir()
            subprocess.run(
                ["git", "init"],
                cwd=repo,
                check=True,
                capture_output=True,
            )
            (repo / "Makefile").write_text(
                "verify:\n\t@echo ok\n",
                encoding="utf-8",
            )
            verify = repo / "verify.sh"
            verify.write_text(
                "#!/bin/sh\necho ok\n",
                encoding="utf-8",
            )
            verify.chmod(0o755)

            proposal = SmartProjectOnboarder(root / "home").propose(repo)

            self.assertEqual(proposal.status, "USER_CHOICE_REQUIRED")
            self.assertIsNone(proposal.profile.get("verify_adapter"))
            self.assertEqual(proposal.policies.get("source_verify"), [])
            self.assertFalse((repo / ".xp").exists())


if __name__ == "__main__":
    unittest.main()
