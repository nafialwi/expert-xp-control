from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from xp.adapters.git import GitAdapter
from xp.adapters.node import NodeAdapter
from xp.adapters.python_runtime import PythonAdapter
from xp.autopilot import AutopilotController
from xp.checkpoint import CheckpointBuilder
from xp.executor import PackageExecutor
from xp.onboarding import SmartProjectOnboarder
from xp.packages import stage_package
from xp.pkgbuild import build_package_from_spec
from xp.project_doctor import ProjectDoctor, discover_project_facts
from xp.project_registry import ProjectRegistry, load_project_profile


FIXTURES = Path(__file__).parent / "fixtures"


def _git(repo: Path, *args: str, check: bool = True):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=check,
    )


def _fixture_repo(root: Path, name: str) -> Path:
    src = FIXTURES / name
    repo = root / name
    shutil.copytree(src, repo)
    _git(repo, "init")
    _git(repo, "config", "user.email", "xp-test@example.invalid")
    _git(repo, "config", "user.name", "XP Acceptance")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    return repo


def _local_remote(root: Path, repo: Path) -> Path:
    bare = root / f"{repo.name}-remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(bare)],
        check=True,
        text=True,
        capture_output=True,
    )
    _git(repo, "remote", "add", "origin", str(bare))
    branch = _git(repo, "branch", "--show-current").stdout.strip()
    _git(repo, "push", "-u", "origin", branch)
    return bare


def _spec(
    path: Path,
    *,
    project_id: str,
    milestone: str,
    operations: list[dict],
    allowed_paths: list[str],
):
    payload = {
        "spec_version": "1.0",
        "package_type": "WORK",
        "project_id": project_id,
        "milestone": milestone,
        "allowed_paths": allowed_paths,
        "operations": operations,
        "human_qa": ["Acceptance QA"],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class UniversalAcceptanceFixtureTests(unittest.TestCase):
    def test_plain_git_registry_package_branch_safepoint_and_lock(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            repo = _fixture_repo(root, "plain-git")
            _local_remote(root, repo)

            profile = load_project_profile(repo)
            ProjectRegistry.for_home(home).register(profile, repo)
            self.assertEqual(
                ProjectRegistry.for_home(home).last_active().project_id,
                profile.project_id,
            )

            spec_path = _spec(
                root / "work.json",
                project_id=profile.project_id,
                milestone="XP07-PLAIN-GIT",
                allowed_paths=["acceptance"],
                operations=[
                    {
                        "type": "ADD_FILE",
                        "path": "acceptance/probe.txt",
                        "content": "plain-git acceptance\n",
                    }
                ],
            )
            package = build_package_from_spec(home, repo, spec_path)

            controller = AutopilotController(home)

            # Protected branch must reject without source mutation.
            before = _git(repo, "status", "--porcelain").stdout
            blocked = controller.run_package(repo, package)
            self.assertNotEqual(blocked.status, "CLEAR")
            self.assertEqual(_git(repo, "status", "--porcelain").stdout, before)
            self.assertFalse((repo / "acceptance/probe.txt").exists())

            _git(repo, "switch", "-c", "work/xp07-plain-git")
            clear = controller.run_package(repo, package)
            self.assertEqual(clear.status, "CLEAR", clear.message)
            self.assertEqual(clear.stage, "HUMAN_QA")
            self.assertTrue((repo / "acceptance/probe.txt").is_file())

            qa = controller.record_human_qa(
                repo, clear.run_id, clear=True, notes="fixture clear"
            )
            self.assertEqual(qa.stage, "READY_TO_LOCK")

            locked = controller.final_lock(repo, clear.run_id, approved=True)
            self.assertEqual(locked.status, "CLEAR", locked.message)
            self.assertEqual(locked.stage, "LOCKED_REMOTE")

            run = controller.state_store.load(clear.run_id)
            checkpoint = Path(run.metadata["checkpoint_dir"])
            self.assertTrue((checkpoint / "CHECKPOINT_STATE.json").is_file())
            self.assertTrue((checkpoint / "SOURCE.zip").is_file())
            self.assertTrue((checkpoint / "SHA256SUMS.txt").is_file())

    def test_node_runtime_discovery_and_npm_verification(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _fixture_repo(Path(td), "node")
            facts = discover_project_facts(repo)
            self.assertIn("node", facts.runtimes)

            result = NodeAdapter(repo).run_script("verify", timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("NODE_VERIFY_CLEAR", result.stdout)

            audit = ProjectDoctor(Path(td)).inspect(repo)
            self.assertEqual(audit.status, "WORK_READY", audit.to_dict())

    def test_python_runtime_discovery_and_python_verification(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _fixture_repo(Path(td), "python")
            facts = discover_project_facts(repo)
            self.assertIn("python", facts.runtimes)

            result = PythonAdapter(
                repo, allowed_modules={"unittest"}
            ).run_module(
                "unittest",
                ["discover", "-s", "tests"],
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            audit = ProjectDoctor(Path(td)).inspect(repo)
            self.assertEqual(audit.status, "WORK_READY", audit.to_dict())

    def test_node_postgres_source_verify_db_approval_and_sql_test_mock_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            repo = _fixture_repo(root, "node-postgres")
            _local_remote(root, repo)
            _git(repo, "switch", "-c", "work/xp07-node-postgres")

            profile = load_project_profile(repo)
            spec = _spec(
                root / "db-work.json",
                project_id=profile.project_id,
                milestone="XP07-NODE-POSTGRES",
                allowed_paths=["src", "db"],
                operations=[
                    {
                        "type": "ADD_FILE",
                        "path": "src/probe.txt",
                        "content": "source clear\n",
                    },
                    {
                        "type": "APPLY_DB_MIGRATION",
                        "path": "db/migration.sql",
                        "content": (
                            "create table if not exists "
                            "xp_plus_acceptance_fixture("
                            "id integer primary key);\n"
                        ),
                    },
                    {
                        "type": "RUN_SQL_TEST",
                        "path": "db/test.sql",
                        "content": "select 1;\n",
                    },
                ],
            )
            package = build_package_from_spec(home, repo, spec)
            controller = AutopilotController(home)

            first = controller.run_package(repo, package)
            self.assertEqual(first.status, "CLEAR", first.message)
            self.assertEqual(first.stage, "DB_APPROVAL_REQUIRED")

            calls = {"migration": 0, "test": 0}

            class FakePSQL:
                def environment_status(self, check_connection=True):
                    return SimpleNamespace(connection_ok=True)

                def apply_file(self, path, single_transaction=True, timeout=900):
                    calls["migration"] += 1
                    return SimpleNamespace(
                        applied=True,
                        returncode=0,
                        stdout="",
                        stderr="",
                    )

                def run_test_file(self, path, timeout=900):
                    calls["test"] += 1
                    return SimpleNamespace(
                        applied=True,
                        returncode=0,
                        stdout="",
                        stderr="",
                    )

            with patch.object(controller, "_psql", return_value=FakePSQL()):
                second = controller.continue_database(
                    repo, first.run_id, approved=True
                )

            self.assertEqual(second.status, "CLEAR", second.message)
            self.assertEqual(second.stage, "HUMAN_QA")
            self.assertEqual(calls, {"migration": 1, "test": 1})

    def test_firebase_static_has_no_postgres_assumption_and_onboarding_verify_is_real(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            repo = _fixture_repo(root, "firebase-static")

            self.assertFalse((repo / "supabase").exists())
            self.assertFalse((repo / "migrations").exists())
            self.assertFalse((repo / "postgres").exists())

            onboarder = SmartProjectOnboarder(home)
            proposal = onboarder.propose(repo)
            self.assertEqual(proposal.status, "PROPOSAL_READY", proposal.to_dict())
            self.assertEqual(proposal.recommended_verify, "verify")
            self.assertIsNone(proposal.profile.get("database_adapter"))
            self.assertNotEqual(proposal.profile.get("verify_adapter"), "generic")

            profile = onboarder.apply(repo, proposal, approved=True)
            self.assertIsNone(profile.database_adapter)

            audit = ProjectDoctor(home).inspect(repo)
            self.assertEqual(audit.status, "WORK_READY", audit.to_dict())
            self.assertFalse(
                any(
                    item.code.startswith("POSTGRES")
                    and item.level == "BLOCKER"
                    for item in audit.findings
                )
            )

            result = NodeAdapter(repo).run_script("verify", timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("FIREBASE_STATIC_VERIFY_CLEAR", result.stdout)

    def test_rollback_safety_restores_first_mutation_when_second_write_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            repo = _fixture_repo(root, "plain-git")
            _git(repo, "switch", "-c", "work/xp07-rollback")
            (repo / "a.txt").write_text("A0\n", encoding="utf-8")
            (repo / "b.txt").write_text("B0\n", encoding="utf-8")
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "rollback baseline")

            profile = load_project_profile(repo)
            spec = _spec(
                root / "rollback.json",
                project_id=profile.project_id,
                milestone="XP07-ROLLBACK",
                allowed_paths=["a.txt", "b.txt"],
                operations=[
                    {
                        "type": "REPLACE_FILE",
                        "path": "a.txt",
                        "content": "A1\n",
                    },
                    {
                        "type": "REPLACE_FILE",
                        "path": "b.txt",
                        "content": "B1\n",
                    },
                ],
            )
            package = build_package_from_spec(home, repo, spec)
            staged = stage_package(package, root / "staged")
            executor = PackageExecutor(repo)

            import xp.executor as executor_module
            real_replace = executor_module.os.replace
            counter = {"n": 0}

            def fail_second(src, dst):
                counter["n"] += 1
                if counter["n"] == 2:
                    raise OSError("synthetic second-write failure")
                return real_replace(src, dst)

            with patch("xp.executor.os.replace", side_effect=fail_second):
                with self.assertRaises(OSError):
                    executor.apply(staged, root / "backups")

            self.assertEqual((repo / "a.txt").read_text(), "A0\n")
            self.assertEqual((repo / "b.txt").read_text(), "B0\n")


if __name__ == "__main__":
    unittest.main()
