from __future__ import annotations

from pathlib import Path

from .state_store import StateStore


class ProjectRootError(ValueError):
    pass


class ProjectService:
    def __init__(self, store: StateStore):
        self.store = store

    def register(
        self,
        project_id: str,
        name: str,
        root_path: Path | str,
        *,
        source_kind: str = "local",
    ) -> dict[str, object]:
        if source_kind not in {"local", "git"}:
            raise ValueError("source_kind must be 'local' or 'git'")

        root = Path(root_path).expanduser()
        try:
            resolved = root.resolve(strict=True)
        except FileNotFoundError as exc:
            raise ProjectRootError(f"project root does not exist: {root}") from exc

        if not resolved.is_dir():
            raise ProjectRootError(f"project root is not a directory: {resolved}")

        return self.store.register_project(
            project_id,
            name,
            str(resolved),
            source_kind=source_kind,
        )

    def list_projects(self) -> list[dict[str, object]]:
        return self.store.list_projects()

    def switch(self, project_id: str) -> dict[str, object]:
        return self.store.set_active_project(project_id)

    def current(self) -> dict[str, object] | None:
        return self.store.get_active_project()
