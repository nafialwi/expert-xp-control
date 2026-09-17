from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from xp.activity import (
    ActivityCategory,
    ActivityStatus,
    ActivityStore,
)
from xp.autopilot import AutopilotController


class AF03VerificationActivityTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()

        subprocess.run(
            ["git", "init", "-q"],
            cwd=repo,
            check=True,
        )

        subprocess.run(
            ["git", "config", "user.name", "AF03 Test"],
            cwd=repo,
            check=True,
        )
        subprocess.run(
            [
                "git",
                "config",
                "user.email",
                "af03@test.invalid",
            ],
            cwd=repo,
            check=True,
        )

        tools = repo / "tools"
        tools.mkdir()

        (repo / "index.html").write_text(
            "fixture\n",
            encoding="utf-8",
        )

        subprocess.run(
            ["git", "add", "."],
            cwd=repo,
            check=True,
        )
        subprocess.run(
            [
                "git",
                "commit",
                "-q",
                "-m",
                "test: seed repository",
            ],
            cwd=repo,
            check=True,
        )

        return repo

    def _command(
        self,
        script: str,
    ) -> dict[str, object]:
        return {
            "purpose": "verify",
            "argv": ["sh", f"tools/{script}"],
            "paths": [
                f"tools/{script}",
                "index.html",
            ],
        }

    def test_successful_verification_records_objective_counts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            repo = self._repo(root)

            first = repo / "tools" / "first.sh"
            second = repo / "tools" / "second.sh"

            first.write_text(
                "#!/bin/sh\n"
                "printf 'first ok\\n'\n",
                encoding="utf-8",
            )
            second.write_text(
                "#!/bin/sh\n"
                "printf 'second ok\\n'\n",
                encoding="utf-8",
            )

            first.chmod(0o755)
            second.chmod(0o755)

            policy = {
                "source_verify": [
                    {
                        "adapter": "generic",
                        "command": "first",
                    },
                    {
                        "adapter": "generic",
                        "command": "second",
                    },
                ],
                "toolchain_commands": {
                    "first": self._command("first.sh"),
                    "second": self._command("second.sh"),
                },
            }

            controller = AutopilotController(home)

            ok, log, status, _ = controller._verify_source(
                repo,
                policy,
                job_id="RUN-AF03-SUCCESS",
            )

            self.assertTrue(ok, log)
            self.assertEqual(status, "CLEAR")

            events = ActivityStore.for_home(
                home
            ).list_for_job(
                "RUN-AF03-SUCCESS"
            )

            self.assertEqual(len(events), 1)

            event = events[0]

            self.assertEqual(
                event.category,
                ActivityCategory.TEST,
            )
            self.assertEqual(
                event.status,
                ActivityStatus.COMPLETED,
            )
            self.assertEqual(
                event.metadata,
                {
                    "passed": 2,
                    "failed": 0,
                    "skipped": 0,
                },
            )
            self.assertFalse(event.provenance.live)

    def test_failed_verification_records_failed_and_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            repo = self._repo(root)

            fail = repo / "tools" / "fail.sh"
            never = repo / "tools" / "never.sh"

            fail.write_text(
                "#!/bin/sh\n"
                "printf 'failed\\n' >&2\n"
                "exit 7\n",
                encoding="utf-8",
            )
            never.write_text(
                "#!/bin/sh\n"
                "printf 'must not run\\n'\n",
                encoding="utf-8",
            )

            fail.chmod(0o755)
            never.chmod(0o755)

            policy = {
                "source_verify": [
                    {
                        "adapter": "generic",
                        "command": "fail",
                    },
                    {
                        "adapter": "generic",
                        "command": "never",
                    },
                ],
                "toolchain_commands": {
                    "fail": self._command("fail.sh"),
                    "never": self._command("never.sh"),
                },
            }

            controller = AutopilotController(home)

            ok, log, status, _ = controller._verify_source(
                repo,
                policy,
                job_id="RUN-AF03-FAIL",
            )

            self.assertFalse(ok)
            self.assertEqual(status, "ERROR")
            self.assertIn("failed", log.lower())
            self.assertNotIn(
                "ambiguous argument",
                log.lower(),
            )

            events = ActivityStore.for_home(
                home
            ).list_for_job(
                "RUN-AF03-FAIL"
            )

            self.assertEqual(len(events), 1)

            event = events[0]

            self.assertEqual(
                event.status,
                ActivityStatus.FAILED,
            )
            self.assertEqual(
                event.metadata,
                {
                    "passed": 0,
                    "failed": 1,
                    "skipped": 1,
                },
            )


if __name__ == "__main__":
    unittest.main()
