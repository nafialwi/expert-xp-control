from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from xp_next.cli import main
from xp_next.runtime import XPRuntime
from xp_next.project_service import ProjectService
from xp_next.worker_selection import ResourceSnapshot


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def init_source(root: Path) -> str:
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Fixture")
    (root / "app.txt").write_text("SAFE\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "baseline")
    return git(root, "rev-parse", "HEAD")


class LocalFixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send(self, payload: dict[str, object]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._send({"status": "ok"})
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self._send(
            {
                "model": "qwen-fixture-local",
                "choices": [
                    {
                        "message": {
                            "content": "The local fixture supports the bounded requested change."
                        }
                    }
                ],
            }
        )


class LoopbackFixtureServer:
    def __enter__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), LocalFixtureHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class HumanWorkCLIFlows(unittest.TestCase):
    def _resources(self):
        return ResourceSnapshot(
            available_memory_mb=1024,
            logical_cpus=4,
            source="test",
        )

    def _operation(self) -> str:
        return json.dumps(
            {
                "operation": "replace_text",
                "path": "app.txt",
                "expected_text": "SAFE\n",
                "new_text": "CHANGED\n",
            }
        )

    def test_work_noninteractive_never_auto_confirms_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            project = base / "project"
            init_source(project)
            with XPRuntime.open(home) as runtime:
                projects = ProjectService(runtime.store)
                projects.register("fixture", "Fixture", project, source_kind="git")
                projects.switch("fixture")

            stdout = StringIO()
            stderr = StringIO()
            with patch(
                "xp_next.cli.ResourceSnapshot.probe_local_linux",
                return_value=self._resources(),
            ), patch("xp_next.cli.sys.stdin", StringIO("")), redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(
                    [
                        "--home", str(home),
                        "work",
                        "--goal", "Change app.txt safely",
                        "--worker-prompt", self._operation(),
                        "--verify-cmd", "python -c \"from pathlib import Path; assert Path('app.txt').read_text() == 'CHANGED\\n'\"",
                    ]
                )

        self.assertEqual(code, 3)
        self.assertIn("Worker yang disarankan: lightweight_local", stdout.getvalue())
        self.assertIn("Konfirmasi worker belum diberikan", stderr.getvalue())

    def test_one_work_command_runs_reviewed_apply_flow_to_completed(self):
        with tempfile.TemporaryDirectory() as tmp, LoopbackFixtureServer() as server:
            base = Path(tmp)
            home = base / "home"
            project = base / "project"
            original_head = init_source(project)
            with XPRuntime.open(home) as runtime:
                projects = ProjectService(runtime.store)
                projects.register("fixture", "Fixture", project, source_kind="git")
                projects.switch("fixture")

            stdout = StringIO()
            stderr = StringIO()
            with patch(
                "xp_next.cli.ResourceSnapshot.probe_local_linux",
                side_effect=[self._resources(), self._resources()],
            ), redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(
                    [
                        "--home", str(home),
                        "work",
                        "--goal", "Change app.txt safely",
                        "--worker-prompt", self._operation(),
                        "--verify-cmd", "python -c \"from pathlib import Path; assert Path('app.txt').read_text() == 'CHANGED\\n'\"",
                        "--qwen-base-url", server.base_url,
                        "--qwen-model", "qwen-fixture-local",
                        "--confirm-worker",
                        "--approve-sandbox",
                        "--apply",
                    ]
                )

            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("XP Next — Work", output)
            self.assertIn("Project: Fixture", output)
            self.assertIn("Worker yang disarankan: lightweight_local", output)
            self.assertIn("XP Next Sandbox Review", output)
            self.assertIn("Hasil akhir: COMPLETED", output)
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual((project / "app.txt").read_text(encoding="utf-8"), "CHANGED\n")
            self.assertEqual(git(project, "rev-parse", "HEAD"), original_head)
            self.assertEqual(git(project, "status", "--short"), "M app.txt")

    def test_work_discard_keeps_original_untouched(self):
        with tempfile.TemporaryDirectory() as tmp, LoopbackFixtureServer() as server:
            base = Path(tmp)
            home = base / "home"
            project = base / "project"
            init_source(project)
            with XPRuntime.open(home) as runtime:
                projects = ProjectService(runtime.store)
                projects.register("fixture", "Fixture", project, source_kind="git")
                projects.switch("fixture")

            stdout = StringIO()
            with patch(
                "xp_next.cli.ResourceSnapshot.probe_local_linux",
                side_effect=[self._resources(), self._resources()],
            ), redirect_stdout(stdout):
                code = main(
                    [
                        "--home", str(home),
                        "work",
                        "--goal", "Change app.txt safely",
                        "--worker-prompt", self._operation(),
                        "--verify-cmd", "python -c \"from pathlib import Path; assert Path('app.txt').read_text() == 'CHANGED\\n'\"",
                        "--qwen-base-url", server.base_url,
                        "--qwen-model", "qwen-fixture-local",
                        "--confirm-worker",
                        "--approve-sandbox",
                        "--discard",
                    ]
                )

            self.assertEqual(code, 4)
            self.assertIn("Hasil akhir: CANCELLED", stdout.getvalue())
            self.assertEqual((project / "app.txt").read_text(encoding="utf-8"), "SAFE\n")
            self.assertEqual(git(project, "status", "--short"), "")


if __name__ == "__main__":
    unittest.main()
