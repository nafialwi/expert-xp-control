from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .recovery_manifest import RecoveryManifestV1


class GitHubReconstructionError(ValueError):
    pass


@dataclass(frozen=True)
class GitCommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class CanonicalGitHubPlan:
    repo_slug: str
    branch: str
    commit_sha: str
    remote_url: str


@dataclass(frozen=True)
class GitHubReconstructionResult:
    destination: Path
    plan: CanonicalGitHubPlan
    head_sha: str


GitRunner = Callable[[tuple[str, ...]], GitCommandResult]


def _github_remote_url(repo_slug: str) -> str:
    return f"https://github.com/{repo_slug}.git"


def build_canonical_github_plan(
    manifest: RecoveryManifestV1,
) -> CanonicalGitHubPlan:
    if not isinstance(manifest, RecoveryManifestV1):
        raise TypeError("manifest must be RecoveryManifestV1")
    if manifest.branch.startswith("-"):
        raise GitHubReconstructionError(
            "canonical branch must not start with '-'"
        )

    return CanonicalGitHubPlan(
        repo_slug=manifest.repo_slug,
        branch=manifest.branch,
        commit_sha=manifest.commit_sha,
        remote_url=_github_remote_url(manifest.repo_slug),
    )


def _default_git_runner(
    command: tuple[str, ...],
) -> GitCommandResult:
    if not isinstance(command, tuple) or not command:
        raise TypeError("git command must be a non-empty tuple")
    if command[0] != "git":
        raise GitHubReconstructionError(
            "only git commands are allowed"
        )

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = ""

    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    return GitCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _run_step(
    runner: GitRunner,
    command: tuple[str, ...],
    *,
    step: str,
) -> GitCommandResult:
    result = runner(command)
    if not isinstance(result, GitCommandResult):
        raise TypeError(
            "git_runner must return GitCommandResult"
        )
    if result.returncode != 0:
        raise GitHubReconstructionError(
            f"git reconstruction step failed: {step}"
        )
    return result


def reconstruct_canonical_github(
    *,
    manifest: RecoveryManifestV1,
    destination: Path,
    git_runner: GitRunner | None = None,
) -> GitHubReconstructionResult:
    if not isinstance(destination, Path):
        raise TypeError("destination must be pathlib.Path")
    if destination.is_symlink():
        raise GitHubReconstructionError(
            "destination symlink is forbidden"
        )
    if destination.exists():
        if not destination.is_dir():
            raise GitHubReconstructionError(
                "destination must be a directory path"
            )
        if any(destination.iterdir()):
            raise GitHubReconstructionError(
                "destination must be empty"
            )

    plan = build_canonical_github_plan(manifest)
    runner = git_runner or _default_git_runner
    if not callable(runner):
        raise TypeError("git_runner must be callable")

    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=".xp-github-reconstruct-",
            dir=str(parent),
        )
    )

    branch_ref = f"refs/heads/{plan.branch}"

    try:
        _run_step(
            runner,
            (
                "git",
                "clone",
                "--no-checkout",
                "--origin",
                "origin",
                plan.remote_url,
                str(staging),
            ),
            step="clone",
        )

        _run_step(
            runner,
            (
                "git",
                "-C",
                str(staging),
                "fetch",
                "--no-tags",
                "origin",
                branch_ref,
            ),
            step="fetch-branch",
        )

        _run_step(
            runner,
            (
                "git",
                "-C",
                str(staging),
                "cat-file",
                "-e",
                f"{plan.commit_sha}^{{commit}}",
            ),
            step="verify-commit-object",
        )

        _run_step(
            runner,
            (
                "git",
                "-C",
                str(staging),
                "merge-base",
                "--is-ancestor",
                plan.commit_sha,
                "FETCH_HEAD",
            ),
            step="verify-commit-on-branch",
        )

        _run_step(
            runner,
            (
                "git",
                "-C",
                str(staging),
                "checkout",
                "--detach",
                plan.commit_sha,
            ),
            step="checkout-exact-commit",
        )

        head = _run_step(
            runner,
            (
                "git",
                "-C",
                str(staging),
                "rev-parse",
                "HEAD",
            ),
            step="verify-head",
        ).stdout.strip().lower()

        if head != plan.commit_sha:
            raise GitHubReconstructionError(
                "reconstructed HEAD does not match manifest commit_sha"
            )

        if destination.exists():
            destination.rmdir()
        staging.replace(destination)

    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise

    return GitHubReconstructionResult(
        destination=destination,
        plan=plan,
        head_sha=head,
    )


__all__ = [
    "CanonicalGitHubPlan",
    "GitCommandResult",
    "GitHubReconstructionError",
    "GitHubReconstructionResult",
    "GitRunner",
    "build_canonical_github_plan",
    "reconstruct_canonical_github",
]
