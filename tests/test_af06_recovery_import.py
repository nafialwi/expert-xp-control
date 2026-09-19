from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from xp.recovery_bundle import (
    INDEX_MEMBER,
    MANIFEST_MEMBER,
    PAYLOAD_PREFIX,
    export_recovery_bundle,
)
from xp.recovery_import import (
    RecoveryImportError,
    restore_recovery_bundle,
    verify_recovery_bundle,
)
from xp.recovery_manifest import RecoveryManifestV1


SHA = "c" * 40


def make_manifest(*paths):
    return RecoveryManifestV1(
        project_id="xp-portable",
        checkpoint="AF06-T4",
        repo_slug="nafialwi/expert-xp-control",
        branch="work/af06-recovery-device-independence",
        commit_sha=SHA,
        created_at_utc="2026-09-18T10:30:00Z",
        required_paths=tuple(paths),
        metadata={"profile": "universal"},
    )


def make_bundle(tmp: Path, *paths):
    root = tmp / "project"
    root.mkdir()
    for rel in paths:
        target = root.joinpath(*rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f"portable:{rel}",
            encoding="utf-8",
        )
    bundle = tmp / "recovery.zip"
    export_recovery_bundle(
        manifest=make_manifest(*paths),
        project_root=root,
        destination=bundle,
    )
    return root, bundle


class AF06RecoveryImportTests(unittest.TestCase):
    def test_verify_and_restore_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            root, bundle = make_bundle(
                tmp,
                "state/checkpoint.json",
                "config/profile.txt",
            )

            verified = verify_recovery_bundle(bundle)

            self.assertEqual(
                verified.manifest.commit_sha,
                SHA,
            )
            self.assertEqual(
                [member.path for member in verified.members],
                [
                    "state/checkpoint.json",
                    "config/profile.txt",
                ],
            )

            destination = tmp / "restored"
            result = restore_recovery_bundle(
                bundle_path=bundle,
                destination=destination,
            )

            self.assertEqual(
                result.restored_paths,
                (
                    "state/checkpoint.json",
                    "config/profile.txt",
                ),
            )
            self.assertEqual(
                (destination / "state" / "checkpoint.json").read_text(
                    encoding="utf-8"
                ),
                (root / "state" / "checkpoint.json").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertTrue(
                (destination / MANIFEST_MEMBER).is_file()
            )

    def test_tampered_payload_checksum_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _, bundle = make_bundle(tmp, "state/a.txt")

            with zipfile.ZipFile(bundle, "a") as zf:
                zf.writestr(
                    PAYLOAD_PREFIX + "state/a.txt",
                    b"tampered",
                )

            with self.assertRaises(RecoveryImportError):
                verify_recovery_bundle(bundle)

    def test_manifest_checksum_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _, bundle = make_bundle(tmp, "state/a.txt")

            rebuilt = tmp / "rebuilt.zip"
            with zipfile.ZipFile(bundle, "r") as source:
                contents = {
                    name: source.read(name)
                    for name in source.namelist()
                }

            manifest = json.loads(
                contents[MANIFEST_MEMBER].decode("utf-8")
            )
            manifest["checkpoint"] = "TAMPERED"
            contents[MANIFEST_MEMBER] = json.dumps(
                manifest,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")

            with zipfile.ZipFile(rebuilt, "w") as target:
                for name, data in contents.items():
                    target.writestr(name, data)

            with self.assertRaisesRegex(
                RecoveryImportError,
                "manifest checksum mismatch",
            ):
                verify_recovery_bundle(rebuilt)

    def test_unexpected_archive_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _, bundle = make_bundle(tmp, "state/a.txt")

            with zipfile.ZipFile(bundle, "a") as zf:
                zf.writestr("extra.txt", b"extra")

            with self.assertRaisesRegex(
                RecoveryImportError,
                "unexpected archive members",
            ):
                verify_recovery_bundle(bundle)

    def test_traversal_archive_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bundle = tmp / "bad.zip"
            with zipfile.ZipFile(bundle, "w") as zf:
                zf.writestr("../escape.txt", b"x")
                zf.writestr(MANIFEST_MEMBER, b"{}")
                zf.writestr(INDEX_MEMBER, b"{}")

            with self.assertRaisesRegex(
                RecoveryImportError,
                "traversal",
            ):
                verify_recovery_bundle(bundle)

    def test_nonempty_destination_is_rejected_before_restore(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _, bundle = make_bundle(tmp, "state/a.txt")
            destination = tmp / "restored"
            destination.mkdir()
            (destination / "keep.txt").write_text(
                "keep",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                RecoveryImportError,
                "destination must be empty",
            ):
                restore_recovery_bundle(
                    bundle_path=bundle,
                    destination=destination,
                )

            self.assertEqual(
                (destination / "keep.txt").read_text(
                    encoding="utf-8"
                ),
                "keep",
            )

    def test_destination_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _, bundle = make_bundle(tmp, "state/a.txt")
            target = tmp / "target"
            target.mkdir()
            destination = tmp / "restored"
            try:
                destination.symlink_to(target, target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation unavailable")

            with self.assertRaisesRegex(
                RecoveryImportError,
                "destination symlink",
            ):
                restore_recovery_bundle(
                    bundle_path=bundle,
                    destination=destination,
                )

    def test_secret_like_payload_is_rejected_on_import(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _, bundle = make_bundle(tmp, "state/a.txt")

            with zipfile.ZipFile(bundle, "r") as source:
                contents = {
                    name: source.read(name)
                    for name in source.namelist()
                }

            secret = (
                b"Authorization: Bearer "
                b"abcdefghijklmnopqrstuvwxyz123456"
            )
            contents[PAYLOAD_PREFIX + "state/a.txt"] = secret

            index = json.loads(
                contents[INDEX_MEMBER].decode("utf-8")
            )
            import hashlib
            index["members"][0]["size"] = len(secret)
            index["members"][0]["sha256"] = hashlib.sha256(
                secret
            ).hexdigest()
            contents[INDEX_MEMBER] = json.dumps(
                index,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")

            rebuilt = tmp / "secret.zip"
            with zipfile.ZipFile(rebuilt, "w") as target:
                for name, data in contents.items():
                    target.writestr(name, data)

            with self.assertRaisesRegex(
                RecoveryImportError,
                "secret-like content",
            ):
                verify_recovery_bundle(rebuilt)


if __name__ == "__main__":
    unittest.main()
