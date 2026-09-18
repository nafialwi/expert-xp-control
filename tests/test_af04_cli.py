from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from xp.ai.task_feedback import TaskCategory, TaskFeedbackStore
from xp.ai.usage_history import AIUsageObservation, UsageHistoryStore


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 18, 5, 15, tzinfo=timezone.utc)


class AF04CLITests(unittest.TestCase):
    def _run_cli(self, home: Path, *args: str):
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run(
            [sys.executable, "-m", "xp.cli", *args],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def _record_usage(self, home: Path, *, job_id="job-1"):
        UsageHistoryStore.for_home(home).record(
            AIUsageObservation(
                record_id=f"record-{job_id}",
                timestamp=NOW,
                job_id=job_id,
                route_id="route-a",
                transport="openai-compatible",
                configured_model="model-a",
                served_model="model-a",
                cost_class="free",
                latency_ms=20.0,
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
                technical_result="completed",
                error_type=None,
            )
        )

    def _write_ai_config(self, home: Path):
        path = home / ".expert-workstation" / "config" / "ai.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "default_route": "route-a",
                    "routes": {
                        "route-a": {
                            "transport": "openai-compatible",
                            "base_url": "https://network.invalid/v1",
                            "model": "model-a",
                            "secret_env": "TEST_AI_KEY",
                            "cost_class": "free",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_root_help_exposes_minimal_af04_commands(self):
        with tempfile.TemporaryDirectory() as td:
            result = self._run_cli(Path(td), "--help")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ai-usage", result.stdout)
        self.assertIn("ai-recommend", result.stdout)

    def test_ai_usage_is_compact_by_default_and_expand_is_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            self._record_usage(home)

            compact = self._run_cli(home, "ai-usage", "job-1")
            expanded = self._run_cli(
                home,
                "ai-usage",
                "job-1",
                "--expand",
            )

        self.assertEqual(compact.returncode, 0, compact.stderr)
        self.assertEqual(expanded.returncode, 0, expanded.stderr)
        self.assertIn("Gratis", compact.stdout)
        self.assertIn("Tidak tersedia", compact.stdout)
        self.assertNotIn("Transport:", compact.stdout)
        self.assertIn("Transport: openai-compatible", expanded.stdout)

    def test_ai_usage_missing_record_is_clear_non_success(self):
        with tempfile.TemporaryDirectory() as td:
            result = self._run_cli(
                Path(td),
                "ai-usage",
                "missing-job",
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "Tidak ada riwayat AI untuk job: missing-job",
            result.stdout + result.stderr,
        )

    def test_ai_recommend_is_compact_default_and_reports_insufficient_data(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            self._write_ai_config(home)
            self._record_usage(home)
            TaskFeedbackStore.for_home(home).set_category(
                "job-1",
                TaskCategory.CODING_DEBUGGING,
                when=NOW,
            )

            compact = self._run_cli(
                home,
                "ai-recommend",
                "coding_debugging",
            )
            expanded = self._run_cli(
                home,
                "ai-recommend",
                "coding_debugging",
                "--expand",
            )

        self.assertEqual(compact.returncode, 0, compact.stderr)
        self.assertEqual(expanded.returncode, 0, expanded.stderr)
        self.assertIn("Rekomendasi awal", compact.stdout)
        self.assertIn("Belum cukup data", compact.stdout)
        self.assertNotIn("Bukti:", compact.stdout)
        self.assertIn("Bukti:", expanded.stdout)
        self.assertIn("Belum diperiksa", expanded.stdout)

    def test_ai_recommend_invalid_category_is_non_success(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            self._write_ai_config(home)
            result = self._run_cli(
                home,
                "ai-recommend",
                "not-a-category",
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "Kategori AI tidak dikenal",
            result.stdout + result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
