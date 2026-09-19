from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xp.recovery_github import (
    CanonicalGitHubPlan,
    GitCommandResult,
    GitHubReconstructionError,
    build_canonical_github_plan,
    reconstruct_canonical_github,
)
from xp.recovery_manifest import RecoveryManifestV1


SHA = "e" * 40
REPO = "nafialwi/expert-xp-control"
BRANCH = "work/af06-recovery-device-independence"


def make_manifest(**overrides):
    data = dict(
        project_id="xp-portable",
        checkpoint="AF06-T6",
        repo_slug=REPO,
        branch=BRANCH,
        commit_sha=SHA,
        created_at_utc="2026-09-18T11:30:00Z",
        required_paths=(),
        metadata={"profile": "universal"},
    )
    data.update(overrides)
    return RecoveryManifestV1(**data)


class RecordingRunner:
    def __init__(
        self,
        *,
        head=SHA,
        fail_step=None,
    ):
        self.head = head
        self.fail_step = fail_step
        self.commands = []

    def __call__(self, command):
        self.commands.append(command)
        index = len(self.commands)

        if self.fail_step == index:
            return GitCommandResult(
                returncode=1,
                stdout="",
                stderr="sensitive output must not surface",
            )

        if command[-2:] == ("rev-parse", "HEAD"):
            return GitCommandResult(
                returncode=0,
                stdout=self.head + "\n",
                stderr="",
            )

        return GitCommandResult(
            returncode=0,
            stdout="",
            stderr="",
        )


class AF06CanonicalGitHubTests(unittest.TestCase):
    def test_plan_uses_canonical_https_github_url(self):
        plan = build_canonical_github_plan(make_manifest())

        self.assertEqual(
            plan,
            CanonicalGitHubPlan(
                repo_slug=REPO,
                branch=BRANCH,
                commit_sha=SHA,
                remote_url=(
                    "https://github.com/"
                    "nafialwi/expert-xp-control.git"
                ),
            ),
        )
        self.assertNotIn("@github.com", plan.remote_url)
        self.assertNotIn("token", plan.remote_url.lower())

    def test_reconstruction_pins_exact_branch_and_commit(self):
        with tempfile.TemporaryDirectory() as td:
            destination = Path(td) / "new-device" / "project"
            runner = RecordingRunner()

            result = reconstruct_canonical_github(
                manifest=make_manifest(),
                destination=destination,
                git_runner=runner,
            )

            self.assertEqual(result.head_sha, SHA)
            self.assertEqual(result.plan.repo_slug, REPO)
            self.assertEqual(result.plan.branch, BRANCH)
            self.assertEqual(len(runner.commands), 6)

            clone = runner.commands[0]
            self.assertEqual(clone[0:5], (
                "git",
                "clone",
                "--no-checkout",
                "--origin",
                "origin",
            ))
            self.assertEqual(
                clone[5],
                "https://github.com/"
                "nafialwi/expert-xp-control.git",
            )

            fetch = runner.commands[1]
            self.assertIn(
                "refs/heads/"
                "work/af06-recovery-device-independence",
                fetch,
            )

            self.assertIn(
                SHA + "^{commit}",
                runner.commands[2],
            )
            self.assertIn(SHA, runner.commands[3])
            self.assertIn("FETCH_HEAD", runner.commands[3])
            self.assertIn(SHA, runner.commands[4])
            self.assertTrue(destination.is_dir())

    def test_wrong_head_fails_closed_and_leaves_no_destination(self):
        with tempfile.TemporaryDirectory() as td:
            destination = Path(td) / "new-device" / "project"
            runner = RecordingRunner(head="f" * 40)

            with self.assertRaisesRegex(
                GitHubReconstructionError,
                "HEAD does not match",
            ):
                reconstruct_canonical_github(
                    manifest=make_manifest(),
                    destination=destination,
                    git_runner=runner,
                )

            self.assertFalse(destination.exists())

    def test_branch_ancestry_failure_leaves_no_destination(self):
        with tempfile.TemporaryDirectory() as td:
            destination = Path(td) / "restore"
            runner = RecordingRunner(fail_step=4)

            with self.assertRaisesRegex(
                GitHubReconstructionError,
                "verify-commit-on-branch",
            ):
                reconstruct_canonical_github(
                    manifest=make_manifest(),
                    destination=destination,
                    git_runner=runner,
                )

            self.assertFalse(destination.exists())

    def test_git_error_does_not_surface_runner_stderr(self):
        with tempfile.TemporaryDirectory() as td:
            destination = Path(td) / "restore"
            runner = RecordingRunner(fail_step=1)

            with self.assertRaises(
                GitHubReconstructionError,
            ) as ctx:
                reconstruct_canonical_github(
                    manifest=make_manifest(),
                    destination=destination,
                    git_runner=runner,
                )

            self.assertNotIn(
                "sensitive output",
                str(ctx.exception),
            )
            self.assertFalse(destination.exists())

    def test_nonempty_destination_is_rejected_before_git(self):
        with tempfile.TemporaryDirectory() as td:
            destination = Path(td) / "restore"
            destination.mkdir()
            (destination / "keep.txt").write_text(
                "keep",
                encoding="utf-8",
            )
            runner = RecordingRunner()

            with self.assertRaisesRegex(
                GitHubReconstructionError,
                "destination must be empty",
            ):
                reconstruct_canonical_github(
                    manifest=make_manifest(),
                    destination=destination,
                    git_runner=runner,
                )

            self.assertEqual(runner.commands, [])
            self.assertEqual(
                (destination / "keep.txt").read_text(
                    encoding="utf-8"
                ),
                "keep",
            )

    def test_destination_symlink_is_rejected_before_git(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "target"
            target.mkdir()
            destination = root / "restore"
            try:
                destination.symlink_to(
                    target,
                    target_is_directory=True,
                )
            except OSError:
                self.skipTest("symlink creation unavailable")

            runner = RecordingRunner()

            with self.assertRaisesRegex(
                GitHubReconstructionError,
                "destination symlink",
            ):
                reconstruct_canonical_github(
                    manifest=make_manifest(),
                    destination=destination,
                    git_runner=runner,
                )

            self.assertEqual(runner.commands, [])

    def test_branch_beginning_with_dash_is_rejected(self):
        # RecoveryManifestV1 currently permits this lexical shape,
        # so reconstruction adds the git-specific fail-closed rule.
        manifest = make_manifest(branch="-unsafe")

        with self.assertRaisesRegex(
            GitHubReconstructionError,
            "must not start",
        ):
            build_canonical_github_plan(manifest)


if __name__ == "__main__":
    unittest.main()
