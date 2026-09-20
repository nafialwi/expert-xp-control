from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from xp_next.hermes_worker import (
    HermesLocalWorker,
    HermesWorkerConfigError,
)
from xp_next.worker_contract import WorkerRequest, WorkerStatus


class HermesWorkerTests(unittest.TestCase):
    def test_remote_model_endpoint_is_rejected(self):
        with self.assertRaises(HermesWorkerConfigError):
            HermesLocalWorker(base_url="https://example.com/v1")

    def test_readiness_requires_binary_and_loopback_health(self):
        worker = HermesLocalWorker(
            binary="/tools/hermes",
            base_url="http://127.0.0.1:18090/v1",
            binary_exists=lambda path: path == "/tools/hermes",
            health_probe=lambda url, timeout: {"status": "ok"},
            context_probe=lambda url, timeout: 65536,
        )
        self.assertEqual(worker.timeout, 480.0)
        readiness = worker.readiness()
        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.status, "READY")
        self.assertEqual(readiness.backend_id, "hermes")
        self.assertEqual(readiness.model_transport, "loopback_http")

    def test_readiness_fails_closed_when_effective_context_is_below_hermes_floor(self):
        worker = HermesLocalWorker(
            binary="/tools/hermes",
            base_url="http://127.0.0.1:18090/v1",
            binary_exists=lambda path: True,
            health_probe=lambda url, timeout: {"status": "ok"},
            context_probe=lambda url, timeout: 32768,
        )
        readiness = worker.readiness()
        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.status, "NEEDS_ATTENTION")
        self.assertIn("32768", readiness.detail)
        self.assertIn("65536", readiness.detail)

    def test_sanitized_environment_does_not_inherit_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "sandbox"
            cwd = root / "project"
            home = root / "home"
            temp = root / "tmp"
            cwd.mkdir(parents=True)
            home.mkdir()
            temp.mkdir()
            worker = HermesLocalWorker(
                binary="/tools/hermes",
                base_url="http://127.0.0.1:18090/v1",
                binary_exists=lambda path: True,
                health_probe=lambda url, timeout: {"status": "ok"},
            )
            old = os.environ.get("SUPER_SECRET_XP_TEST")
            os.environ["SUPER_SECRET_XP_TEST"] = "must-not-leak"
            try:
                env = worker.build_environment(home=home, tmp=temp)
            finally:
                if old is None:
                    os.environ.pop("SUPER_SECRET_XP_TEST", None)
                else:
                    os.environ["SUPER_SECRET_XP_TEST"] = old
            self.assertNotIn("SUPER_SECRET_XP_TEST", env)
            self.assertEqual(env["HOME"], str(home.resolve()))
            self.assertEqual(env["HERMES_HOME"], str((home / ".hermes").resolve()))
            self.assertEqual(env["OPENAI_API_KEY"], "local-fixture-key")
            self.assertEqual(env["NO_PROXY"], "127.0.0.1,localhost,::1")

    def test_isolated_config_disables_tool_search_and_connectors(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            worker = HermesLocalWorker(
                binary="/tools/hermes",
                base_url="http://127.0.0.1:18090/v1",
                binary_exists=lambda path: True,
                health_probe=lambda url, timeout: {"status": "ok"},
                context_probe=lambda url, timeout: 65536,
            )
            worker._write_config(home)
            text = (home / ".hermes" / "config.yaml").read_text(encoding="utf-8")
            self.assertIn("tool_search:", text)
            self.assertIn("enabled: off", text)
            self.assertIn("connectors:", text)
            self.assertIn("enabled: false", text)
            self.assertIn("max_turns: 2", text)

    def test_zero_exit_without_sandbox_mutation_needs_attention(self):
        class Result:
            returncode = 0
            stdout = "I would fix it."
            stderr = ""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sandbox"
            cwd = root / "project"
            home = root / "home"
            temp = root / "tmp"
            cwd.mkdir(parents=True)
            home.mkdir()
            temp.mkdir()
            request = WorkerRequest(
                job_id="job-noop",
                prompt="fix fixture",
                workspace_root=root,
                cwd=cwd,
            )
            worker = HermesLocalWorker(
                binary="/tools/hermes",
                base_url="http://127.0.0.1:18090/v1",
                binary_exists=lambda path: True,
                health_probe=lambda url, timeout: {"status": "ok"},
                context_probe=lambda url, timeout: 65536,
                mutation_probe=lambda project: (),
                runner=lambda *args, **kwargs: Result(),
            )
            result = worker.run(request, home=home, tmp=temp)
            self.assertEqual(result.status, WorkerStatus.NEEDS_ATTENTION)
            self.assertEqual(result.returncode, 0)
            self.assertIn("no sandbox mutation", result.detail.lower())
            self.assertFalse(result.apply_to_original_performed)

    def test_run_uses_isolated_cwd_and_no_original_apply(self):
        captured = {}

        class Result:
            returncode = 0
            stdout = "XP_HERMES_FIXTURE_OK\n"
            stderr = ""

        def runner(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return Result()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sandbox"
            cwd = root / "project"
            home = root / "home"
            temp = root / "tmp"
            cwd.mkdir(parents=True)
            home.mkdir()
            temp.mkdir()
            request = WorkerRequest(
                job_id="job-1",
                prompt="fix fixture",
                workspace_root=root,
                cwd=cwd,
            )
            worker = HermesLocalWorker(
                binary="/tools/hermes",
                base_url="http://127.0.0.1:18090/v1",
                binary_exists=lambda path: True,
                health_probe=lambda url, timeout: {"status": "ok"},
                context_probe=lambda url, timeout: 65536,
                mutation_probe=lambda project: ("calc.py",),
                runner=runner,
            )
            result = worker.run(request, home=home, tmp=temp)
            self.assertEqual(result.status, WorkerStatus.COMPLETED)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.backend_id, "hermes")
            self.assertFalse(result.apply_to_original_performed)
            self.assertEqual(captured["kwargs"]["cwd"], cwd.resolve())
            self.assertEqual(captured["kwargs"]["env"]["HOME"], str(home.resolve()))
            self.assertIn("--provider", captured["cmd"])
            self.assertIn("custom", captured["cmd"])
            self.assertIn("--model", captured["cmd"])
            self.assertIn("local", captured["cmd"])
            self.assertIn("--in", captured["cmd"])
            self.assertIn("--ignore-rules", captured["cmd"])
            tool_index = captured["cmd"].index("-t")
            self.assertEqual(captured["cmd"][tool_index + 1], "file")
            self.assertNotIn("terminal", captured["cmd"])


if __name__ == "__main__":
    unittest.main()
