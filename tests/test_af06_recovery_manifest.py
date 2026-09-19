from __future__ import annotations

import unittest

from xp.recovery_manifest import (
    RecoveryManifestError,
    RecoveryManifestV1,
    SCHEMA_VERSION,
    SOURCE_KIND,
)


SHA = "a" * 40


def make_manifest(**overrides):
    data = dict(
        project_id="segeran-jiwa-pos-next",
        checkpoint="CS-04",
        repo_slug="nafialwi/expert-xp-control",
        branch="work/xp-plus-v1",
        commit_sha=SHA,
        created_at_utc="2026-09-18T09:30:00Z",
        required_paths=(
            "src/xp/ai/agents/runtime_adapter.py",
            "tests/test_af05_runtime_adapter.py",
        ),
        metadata={"profile": "universal"},
    )
    data.update(overrides)
    return RecoveryManifestV1(**data)


class AF06RecoveryManifestTests(unittest.TestCase):
    def test_roundtrip_is_deterministic_and_versioned(self):
        manifest = make_manifest()
        encoded = manifest.to_json()
        decoded = RecoveryManifestV1.from_json(encoded)

        self.assertEqual(decoded, manifest)
        self.assertEqual(decoded.schema_version, SCHEMA_VERSION)
        self.assertEqual(decoded.source_kind, SOURCE_KIND)
        self.assertEqual(encoded, decoded.to_json())

    def test_manifest_uses_repo_slug_not_device_path(self):
        manifest = make_manifest()
        payload = manifest.to_dict()

        self.assertEqual(
            payload["repo_slug"],
            "nafialwi/expert-xp-control",
        )
        self.assertNotIn("device_id", payload)
        self.assertNotIn("home", payload)
        self.assertNotIn("absolute_path", payload)

    def test_absolute_required_path_is_rejected(self):
        with self.assertRaisesRegex(
            RecoveryManifestError,
            "must be relative",
        ):
            make_manifest(required_paths=("/data/data/com.termux/files/home/x",))

    def test_windows_or_traversal_path_is_rejected(self):
        with self.assertRaises(RecoveryManifestError):
            make_manifest(required_paths=("C:\\Users\\me\\project",))

        with self.assertRaisesRegex(
            RecoveryManifestError,
            "traversal",
        ):
            make_manifest(required_paths=("src/../secret.txt",))

    def test_duplicate_required_paths_are_rejected(self):
        with self.assertRaisesRegex(
            RecoveryManifestError,
            "must be unique",
        ):
            make_manifest(required_paths=("src/x.py", "src/x.py"))

    def test_commit_sha_must_be_full(self):
        with self.assertRaisesRegex(
            RecoveryManifestError,
            "40-character",
        ):
            make_manifest(commit_sha="abcdef1")

    def test_repo_slug_must_not_contain_credentials_or_url(self):
        with self.assertRaisesRegex(
            RecoveryManifestError,
            "owner/repository",
        ):
            make_manifest(
                repo_slug="https://token@github.com/owner/repo"
            )

    def test_secret_like_metadata_keys_are_rejected(self):
        for key in (
            "api_key",
            "token",
            "password",
            "credential",
            "Authorization",
        ):
            with self.subTest(key=key):
                with self.assertRaisesRegex(
                    RecoveryManifestError,
                    "secret-like metadata key",
                ):
                    make_manifest(metadata={key: "value"})

    def test_bearer_or_sk_secret_values_are_rejected(self):
        with self.assertRaisesRegex(
            RecoveryManifestError,
            "secret-like metadata value",
        ):
            make_manifest(
                metadata={
                    "note": "Bearer abcdefghijklmnopqrstuvwxyz"
                }
            )

        with self.assertRaisesRegex(
            RecoveryManifestError,
            "secret-like metadata value",
        ):
            make_manifest(
                metadata={"note": "sk-abcdefghijklmnop"}
            )

    def test_unknown_json_fields_fail_closed(self):
        payload = make_manifest().to_dict()
        payload["unexpected"] = True

        with self.assertRaisesRegex(
            RecoveryManifestError,
            "unknown manifest fields",
        ):
            RecoveryManifestV1.from_dict(payload)

    def test_missing_json_fields_fail_closed(self):
        payload = make_manifest().to_dict()
        del payload["commit_sha"]

        with self.assertRaisesRegex(
            RecoveryManifestError,
            "missing manifest fields",
        ):
            RecoveryManifestV1.from_dict(payload)

    def test_wrong_schema_or_source_kind_is_rejected(self):
        with self.assertRaisesRegex(
            RecoveryManifestError,
            "unsupported schema_version",
        ):
            make_manifest(schema_version=2)

        with self.assertRaisesRegex(
            RecoveryManifestError,
            "unsupported source_kind",
        ):
            make_manifest(source_kind="local-device")

    def test_utc_timestamp_is_explicit(self):
        with self.assertRaisesRegex(
            RecoveryManifestError,
            "ending in Z",
        ):
            make_manifest(created_at_utc="2026-09-18T09:30:00+07:00")


if __name__ == "__main__":
    unittest.main()
