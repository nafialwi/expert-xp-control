from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .recovery_import import (
    RecoveryImportError,
    restore_recovery_bundle,
    verify_recovery_bundle,
)
from .recovery_manifest import RecoveryManifestV1


class RecoverySourceMismatchError(RecoveryImportError):
    pass


@dataclass(frozen=True)
class CanonicalRecoverySource:
    repo_slug: str
    branch: str
    commit_sha: str


@dataclass(frozen=True)
class DeviceIndependentRestoreResult:
    destination: Path
    source: CanonicalRecoverySource
    checkpoint: str
    restored_paths: tuple[str, ...]
    manifest: RecoveryManifestV1


def _normalize_expected(
    name: str,
    value: str | None,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RecoverySourceMismatchError(
            f"{name} must be a non-empty string when provided"
        )
    return value.strip()


def _validate_expected_source(
    manifest: RecoveryManifestV1,
    *,
    expected_repo_slug: str | None,
    expected_branch: str | None,
    expected_commit_sha: str | None,
) -> None:
    expected_repo_slug = _normalize_expected(
        "expected_repo_slug",
        expected_repo_slug,
    )
    expected_branch = _normalize_expected(
        "expected_branch",
        expected_branch,
    )
    expected_commit_sha = _normalize_expected(
        "expected_commit_sha",
        expected_commit_sha,
    )

    checks = (
        ("repo_slug", expected_repo_slug, manifest.repo_slug),
        ("branch", expected_branch, manifest.branch),
        ("commit_sha", expected_commit_sha, manifest.commit_sha),
    )
    for label, expected, actual in checks:
        if expected is not None and expected != actual:
            raise RecoverySourceMismatchError(
                f"recovery source mismatch for {label}: "
                f"expected {expected!r}, got {actual!r}"
            )


def restore_on_new_device(
    *,
    bundle_path: Path,
    destination: Path,
    expected_repo_slug: str | None = None,
    expected_branch: str | None = None,
    expected_commit_sha: str | None = None,
) -> DeviceIndependentRestoreResult:
    if not isinstance(bundle_path, Path):
        raise TypeError("bundle_path must be pathlib.Path")
    if not isinstance(destination, Path):
        raise TypeError("destination must be pathlib.Path")

    verified = verify_recovery_bundle(bundle_path)

    _validate_expected_source(
        verified.manifest,
        expected_repo_slug=expected_repo_slug,
        expected_branch=expected_branch,
        expected_commit_sha=expected_commit_sha,
    )

    restored = restore_recovery_bundle(
        bundle_path=bundle_path,
        destination=destination,
    )

    manifest = restored.manifest
    source = CanonicalRecoverySource(
        repo_slug=manifest.repo_slug,
        branch=manifest.branch,
        commit_sha=manifest.commit_sha,
    )

    return DeviceIndependentRestoreResult(
        destination=restored.destination,
        source=source,
        checkpoint=manifest.checkpoint,
        restored_paths=restored.restored_paths,
        manifest=manifest,
    )


__all__ = [
    "CanonicalRecoverySource",
    "DeviceIndependentRestoreResult",
    "RecoverySourceMismatchError",
    "restore_on_new_device",
]
