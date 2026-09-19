from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xp.recovery_bundle import export_recovery_bundle
from xp.recovery_e2e import (
    FreshDeviceRecoveryError,
    recover_project_on_fresh_device,
)
from xp.recovery_github import GitCommandResult
from xp.recovery_manifest import RecoveryManifestV1


SHA = "f" * 40
REPO = "nafialwi/expert-xp-control"
BRANCH = "work/af06-recovery-device-independence"


class RecordingRunner:
    def __init__(self, fail_at=None):
        self.fail_at = fail_at
        self.commands = []

    def __call__(self, command):
        self.commands.append(command)
        if self.fail_at == len(self.commands):
            return GitCommandResult(returncode=1)
        if command[-2:] == ("rev-parse", "HEAD"):
            return GitCommandResult(returncode=0, stdout=SHA + "\n")
        return GitCommandResult(returncode=0)


def make_bundle(tmp):
    src = tmp / "old-device" / "project"
    src.mkdir(parents=True)
    (src / "state").mkdir()
    (src / "state" / "resume.json").write_text(
        '{"checkpoint":"AF06-T7","portable":true}',
        encoding="utf-8",
    )
    manifest = RecoveryManifestV1(
        project_id="xp-portable",
        checkpoint="AF06-T7",
        repo_slug=REPO,
        branch=BRANCH,
        commit_sha=SHA,
        created_at_utc="2026-09-19T00:00:00Z",
        required_paths=("state/resume.json",),
        metadata={"profile":"universal"},
    )
    bundle = tmp / "handoff" / "recovery.zip"
    export_recovery_bundle(
        manifest=manifest,
        project_root=src,
        destination=bundle,
    )
    return bundle


class AF06FreshDeviceE2ETests(unittest.TestCase):
    def test_composes_reconstruct_and_restore(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bundle = make_bundle(tmp)
            result = recover_project_on_fresh_device(
                bundle_path=bundle,
                repo_destination=tmp / "new-device" / "repo",
                state_destination=tmp / "new-device" / "state",
                git_runner=RecordingRunner(),
            )
            self.assertEqual(result.repo_head_sha, SHA)
            self.assertEqual(result.checkpoint, "AF06-T7")
            self.assertEqual(result.restored_paths, ("state/resume.json",))

    def test_bundle_verified_before_git(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bad = tmp / "bad.zip"
            bad.write_bytes(b"not-a-zip")
            runner = RecordingRunner()
            with self.assertRaises(Exception):
                recover_project_on_fresh_device(
                    bundle_path=bad,
                    repo_destination=tmp / "repo",
                    state_destination=tmp / "state",
                    git_runner=runner,
                )
            self.assertEqual(runner.commands, [])

    def test_git_failure_does_not_restore_state(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bundle = make_bundle(tmp)
            state = tmp / "state"
            with self.assertRaises(Exception):
                recover_project_on_fresh_device(
                    bundle_path=bundle,
                    repo_destination=tmp / "repo",
                    state_destination=state,
                    git_runner=RecordingRunner(fail_at=1),
                )
            self.assertFalse(state.exists())

    def test_destinations_must_differ(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bundle = make_bundle(tmp)
            same = tmp / "same"
            with self.assertRaises(FreshDeviceRecoveryError):
                recover_project_on_fresh_device(
                    bundle_path=bundle,
                    repo_destination=same,
                    state_destination=same,
                    git_runner=RecordingRunner(),
                )


if __name__ == "__main__":
    unittest.main()
