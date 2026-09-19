from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from xp.recovery_bundle import (
    BUNDLE_SCHEMA_VERSION,
    INDEX_MEMBER,
    MANIFEST_MEMBER,
    PAYLOAD_PREFIX,
    RecoveryBundleError,
    export_recovery_bundle,
)
from xp.recovery_manifest import RecoveryManifestV1


SHA = "b" * 40


def manifest_for(*paths):
    return RecoveryManifestV1(
        project_id="xp-portable",
        checkpoint="AF06-T3",
        repo_slug="nafialwi/expert-xp-control",
        branch="work/af06-recovery-device-independence",
        commit_sha=SHA,
        created_at_utc="2026-09-18T10:00:00Z",
        required_paths=tuple(paths),
        metadata={"profile": "universal"},
    )


class AF06RecoveryBundleTests(unittest.TestCase):
    def test_export_contains_manifest_index_and_payload(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "project"
            root.mkdir()
            (root / "state").mkdir()
            (root / "state" / "checkpoint.json").write_text(
                '{"checkpoint":"AF06"}',
                encoding="utf-8",
            )
            destination = Path(td) / "recovery.zip"

            result = export_recovery_bundle(
                manifest=manifest_for("state/checkpoint.json"),
                project_root=root,
                destination=destination,
            )

            self.assertTrue(result.bundle_path.is_file())
            self.assertEqual(len(result.members), 1)

            with zipfile.ZipFile(destination) as zf:
                names = set(zf.namelist())
                self.assertIn(MANIFEST_MEMBER, names)
                self.assertIn(INDEX_MEMBER, names)
                self.assertIn(
                    PAYLOAD_PREFIX + "state/checkpoint.json",
                    names,
                )

                manifest_payload = RecoveryManifestV1.from_json(
                    zf.read(MANIFEST_MEMBER).decode("utf-8")
                )
                self.assertEqual(
                    manifest_payload.commit_sha,
                    SHA,
                )

                index = json.loads(
                    zf.read(INDEX_MEMBER).decode("utf-8")
                )
                self.assertEqual(
                    index["bundle_schema_version"],
                    BUNDLE_SCHEMA_VERSION,
                )
                self.assertEqual(len(index["members"]), 1)
                self.assertEqual(
                    index["members"][0]["path"],
                    "state/checkpoint.json",
                )
                self.assertEqual(
                    len(index["members"][0]["sha256"]),
                    64,
                )

    def test_empty_required_paths_exports_metadata_only_bundle(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "project"
            root.mkdir()
            destination = Path(td) / "recovery.zip"

            result = export_recovery_bundle(
                manifest=manifest_for(),
                project_root=root,
                destination=destination,
            )

            self.assertEqual(result.members, ())
            with zipfile.ZipFile(destination) as zf:
                self.assertEqual(
                    set(zf.namelist()),
                    {MANIFEST_MEMBER, INDEX_MEMBER},
                )

    def test_missing_required_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "project"
            root.mkdir()

            with self.assertRaisesRegex(
                RecoveryBundleError,
                "missing",
            ):
                export_recovery_bundle(
                    manifest=manifest_for("state/missing.json"),
                    project_root=root,
                    destination=Path(td) / "out.zip",
                )

    def test_symlink_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "project"
            root.mkdir()
            target = Path(td) / "outside.txt"
            target.write_text("outside", encoding="utf-8")
            link = root / "link.txt"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("symlink creation unavailable")

            with self.assertRaisesRegex(
                RecoveryBundleError,
                "symlink",
            ):
                export_recovery_bundle(
                    manifest=manifest_for("link.txt"),
                    project_root=root,
                    destination=Path(td) / "out.zip",
                )

    def test_secret_like_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "project"
            root.mkdir()
            (root / "state.txt").write_text(
                "Authorization: Bearer "
                "abcdefghijklmnopqrstuvwxyz123456",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                RecoveryBundleError,
                "secret-like content",
            ):
                export_recovery_bundle(
                    manifest=manifest_for("state.txt"),
                    project_root=root,
                    destination=Path(td) / "out.zip",
                )

    def test_destination_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "project"
            root.mkdir()
            destination_target = Path(td) / "target.zip"
            destination_target.write_bytes(b"")
            destination = Path(td) / "out.zip"
            try:
                destination.symlink_to(destination_target)
            except OSError:
                self.skipTest("symlink creation unavailable")

            with self.assertRaisesRegex(
                RecoveryBundleError,
                "destination symlink",
            ):
                export_recovery_bundle(
                    manifest=manifest_for(),
                    project_root=root,
                    destination=destination,
                )

    def test_bundle_member_names_are_portable_relative_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "project"
            root.mkdir()
            (root / "state").mkdir()
            (root / "state" / "a.txt").write_text(
                "portable",
                encoding="utf-8",
            )
            destination = Path(td) / "out.zip"

            export_recovery_bundle(
                manifest=manifest_for("state/a.txt"),
                project_root=root,
                destination=destination,
            )

            with zipfile.ZipFile(destination) as zf:
                for name in zf.namelist():
                    self.assertFalse(name.startswith("/"))
                    self.assertNotIn("\\", name)
                    self.assertNotIn("../", name)


if __name__ == "__main__":
    unittest.main()
