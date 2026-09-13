from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from xp.adapters.base import AdapterReadiness
from xp.adapters.git import GitAdapter
from xp.adapters.node import NodeAdapter
from xp.adapters.postgresql import PostgreSQLAdapter
from xp.adapters.python_runtime import PythonAdapter


class AdapterContractTests(unittest.TestCase):
    def test_capability_names_remain_stable(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            subprocess.run(
                ["git", "init"], cwd=repo, check=True, capture_output=True
            )
            (repo / "package.json").write_text(
                json.dumps({"scripts": {"verify": "echo ok"}}),
                encoding="utf-8",
            )

            self.assertEqual(
                GitAdapter(repo).capabilities(),
                {"git-state", "git-fingerprint", "git-fetch", "git-push"},
            )
            self.assertEqual(
                NodeAdapter(repo).capabilities(),
                {"node-environment", "npm-script"},
            )
            self.assertEqual(
                PythonAdapter(repo).capabilities(),
                {"python-environment", "python-module"},
            )
            self.assertEqual(
                PostgreSQLAdapter().capabilities(),
                {
                    "postgresql-environment",
                    "sql-classification",
                    "psql-file",
                },
            )

    def test_all_builtin_adapters_expose_structured_non_mutating_readiness(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            subprocess.run(
                ["git", "init"], cwd=repo, check=True, capture_output=True
            )
            (repo / "package.json").write_text(
                json.dumps({"scripts": {"verify": "echo ok"}}),
                encoding="utf-8",
            )

            before = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo,
                text=True,
                capture_output=True,
                check=True,
            ).stdout

            adapters = [
                GitAdapter(repo),
                NodeAdapter(repo),
                PythonAdapter(repo),
                PostgreSQLAdapter(),
            ]
            with patch.dict(
                os.environ,
                {
                    "DATABASE_URL":
                    "postgresql://user:password@example.invalid/db"
                },
            ):
                reports = [adapter.readiness() for adapter in adapters]

            for report in reports:
                self.assertIsInstance(report, AdapterReadiness)
                self.assertIn(
                    report.status,
                    {"READY", "READY_WITH_LIMITATIONS", "NOT_READY"},
                )
                self.assertIsInstance(report.capabilities, tuple)

            after = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo,
                text=True,
                capture_output=True,
                check=True,
            ).stdout
            self.assertEqual(before, after)

    def test_postgres_readiness_never_exposes_database_url(self):
        secret = "postgresql://user:super-secret@example.invalid/db"
        with patch.dict(os.environ, {"DATABASE_URL": secret}):
            report = PostgreSQLAdapter().readiness()
        rendered = repr(report)
        self.assertNotIn("super-secret", rendered)
        self.assertNotIn(secret, rendered)


if __name__ == "__main__":
    unittest.main()
