from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from typing import Callable


GitFingerprint = Callable[[Path], dict[str, object]]


def _git_command(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=3,
        env=env,
    )


def _default_git_fingerprint(root: Path) -> dict[str, object]:
    marker = root / ".git"
    if not marker.exists():
        return {
            "available": shutil.which("git") is not None,
            "inside_work_tree": False,
            "branch": None,
            "head": None,
            "dirty": None,
        }

    if shutil.which("git") is None:
        return {
            "available": False,
            "inside_work_tree": None,
            "branch": None,
            "head": None,
            "dirty": None,
        }

    inside = _git_command(root, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return {
            "available": True,
            "inside_work_tree": False,
            "branch": None,
            "head": None,
            "dirty": None,
        }

    head_result = _git_command(root, "rev-parse", "HEAD")
    head = head_result.stdout.strip() if head_result.returncode == 0 else None

    branch_result = _git_command(root, "symbolic-ref", "--short", "-q", "HEAD")
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None

    status_result = _git_command(root, "status", "--porcelain")
    dirty = bool(status_result.stdout) if status_result.returncode == 0 else None

    return {
        "available": True,
        "inside_work_tree": True,
        "branch": branch or None,
        "head": head or None,
        "dirty": dirty,
    }


class ProjectInspector:
    """Bounded, local, read-only project observation."""

    def __init__(self, *, git_fingerprint: GitFingerprint = _default_git_fingerprint):
        self._git_fingerprint = git_fingerprint

    def inspect(self, root_path: Path | str) -> dict[str, object]:
        root = Path(root_path).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError(f"project root is not a directory: {root}")

        markers = {
            "git": (root / ".git").exists(),
            "package_json": (root / "package.json").is_file(),
            "pyproject_toml": (root / "pyproject.toml").is_file(),
            "requirements_txt": (root / "requirements.txt").is_file(),
            "tests_dir": (root / "tests").is_dir(),
            "src_dir": (root / "src").is_dir(),
        }

        stacks: list[str] = []
        if markers["package_json"]:
            stacks.append("node")
        if markers["pyproject_toml"] or markers["requirements_txt"]:
            stacks.append("python")

        git = self._git_fingerprint(root) if markers["git"] else {
            "available": shutil.which("git") is not None,
            "inside_work_tree": False,
            "branch": None,
            "head": None,
            "dirty": None,
        }

        return {
            "root": str(root),
            "markers": markers,
            "stack_hints": stacks,
            "git": git,
            "network_used": False,
        }
