from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from xp.onboarding import OnboardingError, SmartProjectOnboarder
from xp.project_doctor import ProjectDoctor


def _git(repo: Path, *args: str):
    return subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=True
    )


def _repo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "xp-test@example.invalid")
    _git(repo, "config", "user.name", "XP Test")
    return repo


def _profile(repo: Path, *, project_id: str, runtimes, source_verify, database=None):
    xp = repo / ".xp"
    xp.mkdir()
    (xp / "project.json").write_text(
        json.dumps(
            {
                "profile_version": 1,
                "project_id": project_id,
                "name": project_id,
                "runtimes": list(runtimes),
                "source_adapter": "git",
                "database_adapter": database,
                "verify_adapter": "npm-script" if source_verify else None,
                "deployment_adapter": None,
                "metadata": {},
            }
        ),
        encoding="utf-8",
    )
    (xp / "policies.json").write_text(
        json.dumps(
            {
                "protected_branches": ["main", "master"],
                "allowed_branch_prefixes": ["work/", "xp/recovery/"],
                "source_verify": source_verify,
                "deployment": {"production": "DISABLED"},
            }
        ),
        encoding="utf-8",
    )
    (xp / "compatibility.json").write_text(
        json.dumps({"required_commands": ["git"]}),
        encoding="utf-8",
    )


class ProjectDoctorTests(unittest.TestCase):
    def test_legacy_like_empty_verify_is_incomplete(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = _repo(root, "legacy")
            (repo / "package.json").write_text(
                json.dumps({"scripts": {"verify": "node verify.js"}}),
                encoding="utf-8",
            )
            _profile(repo, project_id="legacy", runtimes=[], source_verify=[])
            audit = ProjectDoctor(root).inspect(repo)
            self.assertEqual(audit.status, "PROFILE_INCOMPLETE")
            codes = {finding.code for finding in audit.findings}
            self.assertIn("CANONICAL_VERIFY_MISSING", codes)
            self.assertIn("PROFILE_RUNTIME_MISSING", codes)

    def test_next_like_node_postgres_verify_is_work_ready(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = _repo(root, "next")
            (repo / "package.json").write_text(
                json.dumps({"scripts": {"verify": "npm run test:all"}}),
                encoding="utf-8",
            )
            (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
            (repo / "supabase").mkdir()
            _profile(
                repo,
                project_id="next",
                runtimes=["node", "python"],
                source_verify=[{"adapter": "node", "script": "verify"}],
                database="postgresql",
            )
            audit = ProjectDoctor(root).inspect(repo)
            self.assertEqual(audit.status, "WORK_READY", audit.to_dict())

    def test_unknown_unprofiled_stack_is_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = _repo(root, "unknown")
            (repo / "README.md").write_text("unknown\n", encoding="utf-8")
            audit = ProjectDoctor(root).inspect(repo)
            self.assertEqual(audit.status, "UNPROFILED")
            self.assertIn("UNKNOWN_RUNTIME", {f.code for f in audit.findings})

    def test_single_verify_is_proposed_without_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = _repo(root, "single")
            (repo / "package.json").write_text(
                json.dumps({"scripts": {"verify": "node verify.js", "start": "node app.js"}}),
                encoding="utf-8",
            )
            proposal = SmartProjectOnboarder(root).propose(repo)
            self.assertEqual(proposal.status, "PROPOSAL_READY")
            self.assertEqual(proposal.recommended_verify, "verify")
            self.assertFalse((repo / ".xp").exists())

    def test_multiple_verify_candidates_require_choice(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = _repo(root, "multiple")
            (repo / "package.json").write_text(
                json.dumps({"scripts": {"verify": "node verify.js", "test": "node test.js"}}),
                encoding="utf-8",
            )
            proposal = SmartProjectOnboarder(root).propose(repo)
            self.assertEqual(proposal.status, "USER_CHOICE_REQUIRED")
            self.assertEqual(set(proposal.verify_candidates), {"verify", "test"})
            self.assertFalse((repo / ".xp").exists())

    def test_apply_requires_approval(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = _repo(root, "approved")
            (repo / "package.json").write_text(
                json.dumps({"scripts": {"verify": "node verify.js"}}),
                encoding="utf-8",
            )
            onboarder = SmartProjectOnboarder(root)
            proposal = onboarder.propose(repo)
            with self.assertRaises(OnboardingError):
                onboarder.apply(repo, proposal, approved=False)
            self.assertFalse((repo / ".xp").exists())
            profile = onboarder.apply(repo, proposal, approved=True)
            self.assertEqual(profile.project_id, "approved")
            self.assertTrue((repo / ".xp" / "project.json").is_file())

    def test_existing_profile_is_audit_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = _repo(root, "existing")
            (repo / "package.json").write_text(
                json.dumps({"scripts": {"verify": "node verify.js"}}),
                encoding="utf-8",
            )
            _profile(
                repo,
                project_id="existing",
                runtimes=["node"],
                source_verify=[{"adapter": "node", "script": "verify"}],
            )
            before = (repo / ".xp" / "project.json").read_bytes()
            proposal = SmartProjectOnboarder(root).propose(repo)
            self.assertEqual(proposal.status, "ALREADY_PROFILED")
            self.assertEqual((repo / ".xp" / "project.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
