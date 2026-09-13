from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .project_registry import (
    ProjectProfileError,
    ProjectRegistry,
    ProjectSummary,
    load_project_profile,
)


@dataclass(frozen=True)
class ProjectSelection:
    project: ProjectSummary | None
    source: str  # cwd | last_active | none
    repo_root: str | None = None
    detail: str = ""


class ProjectSessionResolver:
    """Resolve the project for the current XP process without mutating registry.

    CWD-based selection is ephemeral. The persisted ``last_active`` value remains
    the fallback and is changed only by explicit actions such as
    ``xp project switch``.
    """

    def __init__(self, home: Path):
        self.home = Path(home).expanduser().resolve()
        self.registry = ProjectRegistry.for_home(self.home)

    @staticmethod
    def _repo_root(cwd: Path) -> Path | None:
        current = Path(cwd).expanduser().resolve()
        candidates = (current, *current.parents)
        for candidate in candidates:
            if (candidate / ".git").exists():
                return candidate
        return None

    def _cwd_project(self, cwd: Path) -> ProjectSelection | None:
        root = self._repo_root(cwd)
        if root is None:
            return None

        profile_path = root / ".xp" / "project.json"
        if not profile_path.is_file():
            return None

        try:
            profile = load_project_profile(root)
        except (ProjectProfileError, ValueError, OSError):
            return None

        for item in self.registry.list_projects():
            if item.project_id != profile.project_id or not item.repo_path:
                continue
            try:
                registered = Path(item.repo_path).expanduser().resolve()
            except OSError:
                continue
            if registered == root:
                return ProjectSelection(
                    project=item,
                    source="cwd",
                    repo_root=str(root),
                    detail="CWD repository profile matched registered project.",
                )

        return None

    def resolve(self, cwd: Path | None = None) -> ProjectSelection:
        cwd = Path.cwd() if cwd is None else Path(cwd)
        selected = self._cwd_project(cwd)
        if selected is not None:
            return selected

        fallback = self.registry.last_active()
        if fallback is not None:
            return ProjectSelection(
                project=fallback,
                source="last_active",
                repo_root=fallback.repo_path,
                detail="No registered XP project matched the CWD repository.",
            )

        return ProjectSelection(
            project=None,
            source="none",
            repo_root=None,
            detail="No CWD project and no persisted last_active project.",
        )
