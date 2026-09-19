from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xp.recovery_bundle import export_recovery_bundle
from xp.recovery_device import (
    CanonicalRecoverySource,
    DeviceIndependentRestoreResult,
    RecoverySourceMismatchError,
    restore_on_new_device,
)
from xp.recovery_manifest import RecoveryManifestV1


SHA = "d" * 40
REPO = "nafialwi/expert-xp-control"
BRANCH = "work/af06-recovery-device-independence"


def make_manifest(*paths):
    return RecoveryManifestV1(
        project_id="xp-portable",
        checkpoint="AF06-T5",
        repo_slug=REPO,
        branch=BRANCH,
        commit_sha=SHA,
        created_at_utc="2026-09-18T11:00:00Z",
        required_paths=tuple(paths),
        metadata={"profile": "universal"},
    )


def make_bundle(tmp: Path, source_folder: str = "device-a"):
    source_root = tmp / source_folder / "workspace" / "project"
    source_root.mkdir(parents=True)

    (source_root / "state").mkdir()
    (source_root / "state" / "resume.json").write_text(
        '{"checkpoint":"AF06-T5","portable":true}',
        encoding="utf-8",
    )

    (source_root / "profile").mkdir()
    (source_root / "profile" / "project.txt").write_text(
        "xp-portable",
        encoding="utf-8",
    )

    bundle = tmp / source_folder / "recovery.zip"
    export_recovery_bundle(
        manifest=make_manifest(
            "state/resume.json",
            "profile/project.txt",
        ),
        project_root=source_root,
        destination=bundle,
    )
    return source_root, bundle


class AF06DeviceIndependentRestoreTests(unittest.TestCase):
    def test_restore_can_move_between_unrelated_device_paths(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            source_root, bundle = make_bundle(
                tmp,
                source_folder="old-device",
            )

            destination = (
                tmp
                / "completely-different-device"
                / "fresh-install"
                / "restored-project"
            )

            result = restore_on_new_device(
                bundle_path=bundle,
                destination=destination,
                expected_repo_slug=REPO,
                expected_branch=BRANCH,
                expected_commit_sha=SHA,
            )

            self.assertIsInstance(
                result,
                DeviceIndependentRestoreResult,
            )
            self.assertNotEqual(
                source_root.parent.parent,
                destination.parent.parent,
            )
            self.assertEqual(
                result.source,
                CanonicalRecoverySource(
                    repo_slug=REPO,
                    branch=BRANCH,
                    commit_sha=SHA,
                ),
            )
            self.assertEqual(result.checkpoint, "AF06-T5")
            self.assertEqual(
                result.restored_paths,
                (
                    "state/resume.json",
                    "profile/project.txt",
                ),
            )
            self.assertEqual(
                (destination / "state" / "resume.json").read_text(
                    encoding="utf-8"
                ),
                '{"checkpoint":"AF06-T5","portable":true}',
            )

    def test_restore_result_contains_canonical_source_not_old_device_path(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            source_root, bundle = make_bundle(tmp)

            destination = tmp / "new-device" / "project"
            result = restore_on_new_device(
                bundle_path=bundle,
                destination=destination,
            )

            serialized = result.manifest.to_json()

            self.assertEqual(result.source.repo_slug, REPO)
            self.assertEqual(result.source.branch, BRANCH)
            self.assertEqual(result.source.commit_sha, SHA)
            self.assertNotIn(str(source_root), serialized)
            self.assertNotIn(str(destination), serialized)
            self.assertNotIn("device_id", serialized)

    def test_repo_mismatch_fails_before_destination_creation(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _, bundle = make_bundle(tmp)
            destination = tmp / "new-device" / "project"

            with self.assertRaisesRegex(
                RecoverySourceMismatchError,
                "repo_slug",
            ):
                restore_on_new_device(
                    bundle_path=bundle,
                    destination=destination,
                    expected_repo_slug="other/repository",
                )

            self.assertFalse(destination.exists())

    def test_branch_mismatch_fails_before_destination_creation(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _, bundle = make_bundle(tmp)
            destination = tmp / "new-device" / "project"

            with self.assertRaisesRegex(
                RecoverySourceMismatchError,
                "branch",
            ):
                restore_on_new_device(
                    bundle_path=bundle,
                    destination=destination,
                    expected_branch="main",
                )

            self.assertFalse(destination.exists())

    def test_commit_mismatch_fails_before_destination_creation(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _, bundle = make_bundle(tmp)
            destination = tmp / "new-device" / "project"

            with self.assertRaisesRegex(
                RecoverySourceMismatchError,
                "commit_sha",
            ):
                restore_on_new_device(
                    bundle_path=bundle,
                    destination=destination,
                    expected_commit_sha="e" * 40,
                )

            self.assertFalse(destination.exists())

    def test_empty_expected_source_value_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _, bundle = make_bundle(tmp)

            with self.assertRaisesRegex(
                RecoverySourceMismatchError,
                "non-empty",
            ):
                restore_on_new_device(
                    bundle_path=bundle,
                    destination=tmp / "restore",
                    expected_repo_slug="   ",
                )

    def test_corrupt_bundle_is_rejected_without_partial_restore(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bundle = tmp / "broken.zip"
            bundle.write_bytes(b"not-a-zip")
            destination = tmp / "restore"

            with self.assertRaises(Exception):
                restore_on_new_device(
                    bundle_path=bundle,
                    destination=destination,
                )

            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
