from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


class RuntimePathError(RuntimeError):
    pass


def _absolute_without_symlink_resolution(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    state: Path
    database: Path
    artifacts: Path
    workspaces: Path
    logs: Path

    @classmethod
    def resolve(cls, home: Path | str | None = None) -> "RuntimePaths":
        requested = (
            Path(home)
            if home is not None
            else Path(os.environ.get("XP_NEXT_HOME", "~/.xp-next"))
        )
        root = _absolute_without_symlink_resolution(requested)
        state = root / "state"
        return cls(
            root=root,
            state=state,
            database=state / "xp-next.sqlite3",
            artifacts=root / "artifacts",
            workspaces=root / "workspaces",
            logs=root / "logs",
        )

    @staticmethod
    def _ensure_directory(path: Path) -> None:
        if path.is_symlink():
            raise RuntimePathError(f"runtime path must not be a symlink: {path}")
        if path.exists() and not path.is_dir():
            raise RuntimePathError(f"runtime path is not a directory: {path}")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            path.chmod(0o700)
        except OSError:
            # Some filesystems may not expose POSIX permission semantics.
            pass

    def ensure(self) -> "RuntimePaths":
        self._ensure_directory(self.root)
        for path in (self.state, self.artifacts, self.workspaces, self.logs):
            self._ensure_directory(path)
        return self
