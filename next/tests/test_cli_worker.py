from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from xp_next.cli import main
from xp_next.worker_selection import ResourceSnapshot


class WorkerCLIFlows(unittest.TestCase):
    def _prompt(self) -> str:
        return json.dumps(
            {
                "operation": "replace_text",
                "path": "app.txt",
                "expected_text": "SAFE\n",
                "new_text": "CHANGED\n",
            }
        )

    def _resources(self):
        return ResourceSnapshot(
            available_memory_mb=1024,
            logical_cpus=4,
            source="test",
        )

    def test_choose_confirm_prints_human_recommendation_and_confirmation(self):
        stdout = StringIO()
        stderr = StringIO()
        with patch(
            "xp_next.cli.ResourceSnapshot.probe_local_linux",
            side_effect=[self._resources(), self._resources()],
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                [
                    "worker",
                    "choose",
                    "--prompt",
                    self._prompt(),
                    "--confirm",
                ]
            )
        self.assertEqual(code, 0)
        output = stdout.getvalue()
        self.assertIn("Worker yang disarankan: lightweight_local", output)
        self.assertIn("Worker dikonfirmasi: lightweight_local", output)
        self.assertEqual(stderr.getvalue(), "")

    def test_choose_decline_returns_distinct_cancel_code(self):
        stdout = StringIO()
        with patch(
            "xp_next.cli.ResourceSnapshot.probe_local_linux",
            side_effect=[self._resources(), self._resources()],
        ), redirect_stdout(stdout):
            code = main(
                [
                    "worker",
                    "choose",
                    "--prompt",
                    self._prompt(),
                    "--decline",
                ]
            )
        self.assertEqual(code, 4)
        self.assertIn("Pemilihan worker dibatalkan", stdout.getvalue())

    def test_noninteractive_without_decision_never_auto_confirms(self):
        stdout = StringIO()
        stderr = StringIO()
        fake_stdin = StringIO("")
        with patch(
            "xp_next.cli.ResourceSnapshot.probe_local_linux",
            return_value=self._resources(),
        ), patch("xp_next.cli.sys.stdin", fake_stdin), redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                [
                    "worker",
                    "choose",
                    "--prompt",
                    self._prompt(),
                ]
            )
        self.assertEqual(code, 3)
        self.assertIn("Konfirmasi belum diberikan", stderr.getvalue())
        self.assertNotIn("Worker dikonfirmasi", stdout.getvalue())

    def test_explicit_incompatible_worker_fails_without_fallback(self):
        stdout = StringIO()
        with patch(
            "xp_next.cli.ResourceSnapshot.probe_local_linux",
            return_value=self._resources(),
        ), redirect_stdout(stdout):
            code = main(
                [
                    "worker",
                    "choose",
                    "--prompt",
                    "inspect project and fix the bug",
                    "--backend",
                    "lightweight_local",
                    "--confirm",
                ]
            )
        self.assertEqual(code, 2)
        output = stdout.getvalue()
        self.assertIn("Worker belum dapat dipilih", output)
        self.assertIn("No fallback was attempted", output)

    def test_prompt_file_is_supported_without_exposing_internal_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "operation.json"
            path.write_text(self._prompt(), encoding="utf-8")
            stdout = StringIO()
            with patch(
                "xp_next.cli.ResourceSnapshot.probe_local_linux",
                side_effect=[self._resources(), self._resources()],
            ), redirect_stdout(stdout):
                code = main(
                    [
                        "worker",
                        "choose",
                        "--prompt-file",
                        str(path),
                        "--confirm",
                    ]
                )
        self.assertEqual(code, 0)
        self.assertIn("lightweight_local", stdout.getvalue())

    def test_json_mode_remains_machine_readable(self):
        stdout = StringIO()
        with patch(
            "xp_next.cli.ResourceSnapshot.probe_local_linux",
            side_effect=[self._resources(), self._resources()],
        ), redirect_stdout(stdout):
            code = main(
                [
                    "worker",
                    "choose",
                    "--prompt",
                    self._prompt(),
                    "--confirm",
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(lines[0]["selection"]["backend_id"], "lightweight_local")
        self.assertEqual(lines[1]["confirmation"]["status"], "CONFIRMED")


if __name__ == "__main__":
    unittest.main()
