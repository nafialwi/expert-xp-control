from __future__ import annotations

from dataclasses import dataclass
import shutil
import subprocess
from pathlib import Path


class IsolationError(RuntimeError):
    pass


_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", "node_modules"}
_JOB_ID_ALLOWED = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789-_."
)

_SENSITIVE_NAMES = {
    ".env",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".git-credentials",
    "auth.json",
    "credentials",
    "credentials.json",
}


@dataclass(frozen=True)
class IsolatedWorkspace:
    job_id: str
    source: Path
    root: Path
    project: Path
    home: Path
    tmp: Path
    baseline_head: str
    containment: str = "isolated_copy_sanitized_env_best_effort_network_block"


def _run_git(project: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(project), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return proc.stdout.strip()


def _is_sensitive(name: str) -> bool:
    return name in _SENSITIVE_NAMES or name.startswith(".env.")


def _copy_bounded(
    source: Path,
    target: Path,
    *,
    max_files: int = 1000,
    max_total_bytes: int = 32 * 1024 * 1024,
) -> None:
    count = 0
    total = 0
    for path in sorted(source.rglob("*")):
        rel = path.relative_to(source)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        if path.is_symlink():
            raise IsolationError(f"source symlink is not allowed: {rel.as_posix()}")
        if path.is_dir():
            (target / rel).mkdir(parents=True, exist_ok=True)
            continue
        if not path.is_file():
            continue
        if _is_sensitive(path.name):
            continue
        count += 1
        size = path.stat().st_size
        total += size
        if count > max_files or total > max_total_bytes:
            raise IsolationError("source exceeds isolated-copy safety limit")
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def validate_job_id(job_id: str) -> str:
    value = str(job_id)
    if (
        not value
        or value != value.strip()
        or len(value) > 120
        or value in {".", ".."}
        or any(ch not in _JOB_ID_ALLOWED for ch in value)
    ):
        raise ValueError(
            "job_id must be 1-120 safe ASCII characters: letters, digits, -_."
        )
    return value


def prepare_isolated_workspace(
    source_root: Path | str,
    destination_parent: Path | str,
    *,
    job_id: str,
) -> IsolatedWorkspace:
    safe_job_id = validate_job_id(job_id)

    source = Path(source_root).expanduser().resolve(strict=True)
    if not source.is_dir():
        raise IsolationError("source_root must be a directory")

    parent = Path(destination_parent).expanduser().resolve()
    root = parent / safe_job_id
    try:
        root.relative_to(source)
    except ValueError:
        pass
    else:
        raise IsolationError("isolated workspace must not be inside source project")

    if root.exists():
        raise IsolationError(f"isolated workspace already exists: {root}")

    project = root / "project"
    home = root / "home"
    temp = root / "tmp"
    project.mkdir(parents=True, mode=0o700)
    home.mkdir(mode=0o700)
    temp.mkdir(mode=0o700)

    try:
        _copy_bounded(source, project)
        _run_git(project, "init", "-q")
        _run_git(project, "config", "user.email", "xp-next-sandbox@example.invalid")
        _run_git(project, "config", "user.name", "XP Next Sandbox")
        _run_git(project, "config", "core.hooksPath", "/dev/null")
        _run_git(project, "config", "commit.gpgsign", "false")
        _run_git(project, "add", ".")
        subprocess.run(
            ["git", "-C", str(project), "commit", "-qm", "xp-next isolated baseline"],
            check=True,
            timeout=15,
        )
        baseline = _run_git(project, "rev-parse", "HEAD")
        if _run_git(project, "remote"):
            raise IsolationError("isolated workspace must not contain Git remotes")
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise

    return IsolatedWorkspace(
        job_id=safe_job_id,
        source=source,
        root=root,
        project=project,
        home=home,
        tmp=temp,
        baseline_head=baseline,
    )


def workspace_changed_paths(project_root: Path | str) -> tuple[str, ...]:
    project = Path(project_root).expanduser().resolve(strict=True)
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(project),
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--no-renames",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    paths: list[str] = []
    for record in proc.stdout.split("\0"):
        if not record:
            continue
        if len(record) < 4 or record[2] != " ":
            raise IsolationError(f"unexpected Git porcelain record: {record!r}")
        path = record[3:]
        if not path:
            raise IsolationError("empty changed path from Git status")
        paths.append(path)
    return tuple(sorted(set(paths)))
