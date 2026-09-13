from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from xp.adapters.base import AdapterError
from xp.adapters.generic import GenericToolchainAdapter
from xp.autopilot import AutopilotController
from xp.project_doctor import ProjectDoctor


class GenericToolchainAdapterTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "static-fixture"
        repo.mkdir()
        subprocess.run(
            ["git", "init"], cwd=repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.email", "xp-test@example.invalid"],
            cwd=repo, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "XP Test"],
            cwd=repo, check=True,
        )
        tools = repo / "tools"
        tools.mkdir()
        script = tools / "verify.sh"
        script.write_text(
            "#!/bin/sh\n"
            "printf 'generic fixture ok\\n'\n"
            "printf 'TOKEN=do-not-leak\\n'\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        (repo / "index.html").write_text(
            "<h1>static</h1>\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "fixture"],
            cwd=repo, check=True, capture_output=True,
        )
        return repo

    @staticmethod
    def _declarations():
        return {
            "verify-static": {
                "purpose": "verify",
                "argv": ["sh", "tools/verify.sh"],
                "cwd": ".",
                "timeout": 30,
                "paths": ["tools/verify.sh", "index.html"],
            }
        }

    def test_declared_generic_command_runs_without_shell_and_redacts_output(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            adapter = GenericToolchainAdapter(repo, self._declarations())
            result = adapter.run("verify-static")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("generic fixture ok", result.stdout)
            self.assertNotIn("do-not-leak", result.stdout)
            self.assertIn("[REDACTED]", result.stdout)
            self.assertTrue(adapter.readiness().ready)

    def test_undeclared_command_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            adapter = GenericToolchainAdapter(repo, self._declarations())
            with self.assertRaisesRegex(AdapterError, "not declared"):
                adapter.run("deploy")

    def test_outside_repo_cwd_or_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = self._repo(root)
            declarations = [
                {
                    "bad": {
                        "purpose": "verify",
                        "argv": ["sh", "tools/verify.sh"],
                        "cwd": "../outside",
                    }
                },
                {
                    "bad": {
                        "purpose": "verify",
                        "argv": ["sh", "tools/verify.sh"],
                        "paths": ["../outside.txt"],
                    }
                },
            ]
            for declaration in declarations:
                with self.assertRaisesRegex(
                    AdapterError, "outside repository"
                ):
                    GenericToolchainAdapter(repo, declaration)

    def test_deploy_and_direct_network_actions_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            with self.assertRaisesRegex(
                AdapterError, "unsupported purpose"
            ):
                GenericToolchainAdapter(
                    repo,
                    {
                        "deploy": {
                            "purpose": "deploy",
                            "argv": ["sh", "tools/verify.sh"],
                        }
                    },
                )
            with self.assertRaisesRegex(
                AdapterError, "blocked network/deploy"
            ):
                GenericToolchainAdapter(
                    repo,
                    {
                        "net": {
                            "purpose": "verify",
                            "argv": ["curl", "https://example.com"],
                        }
                    },
                )

    def test_sensitive_environment_is_not_forwarded(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            script = repo / "tools" / "env.sh"
            script.write_text(
                "#!/bin/sh\n"
                "printf 'TOKEN=%s\\n' \"${TOKEN-unset}\"\n"
                "printf 'DATABASE_URL=%s\\n' \"${DATABASE_URL-unset}\"\n",
                encoding="utf-8",
            )
            script.chmod(0o755)
            declarations = {
                "env-check": {
                    "purpose": "test",
                    "argv": ["sh", "tools/env.sh"],
                    "paths": ["tools/env.sh"],
                }
            }
            with patch.dict(
                os.environ,
                {
                    "TOKEN": "very-secret-token",
                    "DATABASE_URL":
                    "postgresql://user:pw@example.invalid/db",
                },
            ):
                result = GenericToolchainAdapter(
                    repo, declarations
                ).run("env-check")

            self.assertEqual(result.returncode, 0)
            self.assertNotIn("very-secret-token", result.stdout)
            self.assertNotIn("postgresql://", result.stdout)

    def test_generic_static_fixture_is_work_ready_and_verifies(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            repo = self._repo(root)
            xp = repo / ".xp"
            xp.mkdir()
            (xp / "project.json").write_text(
                json.dumps(
                    {
                        "profile_version": 1,
                        "project_id": "static-fixture",
                        "name": "Static Fixture",
                        "runtimes": ["generic"],
                        "source_adapter": "git",
                        "database_adapter": None,
                        "verify_adapter": "generic",
                        "deployment_adapter": None,
                        "metadata": {},
                    }
                ),
                encoding="utf-8",
            )
            policy = {
                "source_verify": [
                    {"adapter": "generic", "command": "verify-static"}
                ],
                "toolchain_commands": self._declarations(),
                "protected_branches": ["main", "master"],
                "allowed_branch_prefixes": ["work/"],
            }
            (xp / "policies.json").write_text(
                json.dumps(policy), encoding="utf-8"
            )
            (xp / "compatibility.json").write_text(
                json.dumps({"required_commands": ["git", "sh"]}),
                encoding="utf-8",
            )

            audit = ProjectDoctor(home).inspect(repo)
            self.assertEqual(
                audit.status, "WORK_READY", audit.to_dict()
            )

            before = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo,
                text=True,
                capture_output=True,
                check=True,
            ).stdout
            ok, log, warning_status, _ = (
                AutopilotController(home)._verify_source(repo, policy)
            )
            after = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo,
                text=True,
                capture_output=True,
                check=True,
            ).stdout

            self.assertTrue(ok, log)
            self.assertEqual(warning_status, "CLEAR")
            self.assertIn("generic fixture ok", log)
            self.assertNotIn("do-not-leak", log)
            self.assertEqual(before, after)

    def test_verification_that_mutates_source_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            repo = self._repo(root)
            script = repo / "tools" / "mutate.sh"
            script.write_text(
                "#!/bin/sh\nprintf 'changed\\n' >> index.html\n",
                encoding="utf-8",
            )
            script.chmod(0o755)
            policy = {
                "source_verify": [
                    {"adapter": "generic", "command": "mutate"}
                ],
                "toolchain_commands": {
                    "mutate": {
                        "purpose": "verify",
                        "argv": ["sh", "tools/mutate.sh"],
                        "paths": ["tools/mutate.sh", "index.html"],
                    }
                },
            }
            ok, log, status, _ = (
                AutopilotController(home)._verify_source(repo, policy)
            )
            self.assertFalse(ok)
            self.assertEqual(status, "ERROR")
            self.assertIn("mutated source", log.lower())


if __name__ == "__main__":
    unittest.main()
