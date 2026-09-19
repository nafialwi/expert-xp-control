from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .recovery_device import restore_on_new_device
from .recovery_github import GitRunner, reconstruct_canonical_github
from .recovery_import import verify_recovery_bundle


class FreshDeviceRecoveryError(ValueError):
    pass


@dataclass(frozen=True)
class FreshDeviceRecoveryResult:
    repo_destination: Path
    state_destination: Path
    repo_head_sha: str
    checkpoint: str
    restored_paths: tuple[str, ...]


def recover_project_on_fresh_device(
    *,
    bundle_path: Path,
    repo_destination: Path,
    state_destination: Path,
    git_runner: GitRunner | None = None,
) -> FreshDeviceRecoveryResult:
    if not isinstance(bundle_path, Path):
        raise TypeError("bundle_path must be pathlib.Path")
    if not isinstance(repo_destination, Path):
        raise TypeError("repo_destination must be pathlib.Path")
    if not isinstance(state_destination, Path):
        raise TypeError("state_destination must be pathlib.Path")
    if repo_destination == state_destination:
        raise FreshDeviceRecoveryError(
            "repo and state destinations must be different"
        )

    verified = verify_recovery_bundle(bundle_path)
    manifest = verified.manifest

    reconstructed = reconstruct_canonical_github(
        manifest=manifest,
        destination=repo_destination,
        git_runner=git_runner,
    )

    restored = restore_on_new_device(
        bundle_path=bundle_path,
        destination=state_destination,
        expected_repo_slug=manifest.repo_slug,
        expected_branch=manifest.branch,
        expected_commit_sha=manifest.commit_sha,
    )

    if reconstructed.head_sha != manifest.commit_sha:
        raise FreshDeviceRecoveryError(
            "reconstructed HEAD does not match recovery manifest"
        )
    if (
        restored.source.repo_slug != manifest.repo_slug
        or restored.source.branch != manifest.branch
        or restored.source.commit_sha != manifest.commit_sha
    ):
        raise FreshDeviceRecoveryError(
            "restored canonical source does not match recovery manifest"
        )

    return FreshDeviceRecoveryResult(
        repo_destination=reconstructed.destination,
        state_destination=restored.destination,
        repo_head_sha=reconstructed.head_sha,
        checkpoint=restored.checkpoint,
        restored_paths=restored.restored_paths,
    )
