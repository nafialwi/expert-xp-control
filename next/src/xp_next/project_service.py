from __future__ import annotations

from pathlib import Path

from .project_context import ProjectContextBuilder
from .project_inspector import ProjectInspector
from .state_store import ProjectNotFound, StateStore
from .task_contract import TaskIntent


class ProjectRootError(ValueError):
    pass


class ProjectService:
    def __init__(
        self,
        store: StateStore,
        *,
        inspector: ProjectInspector | None = None,
        context_builder: ProjectContextBuilder | None = None,
    ):
        self.store = store
        self.inspector = inspector or ProjectInspector()
        self.context_builder = context_builder or ProjectContextBuilder()

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

    def _resolve_project(self, project_id: str | None) -> dict[str, object]:
        if project_id is None:
            project = self.current()
            if project is None:
                raise ProjectNotFound("no active project")
            return project
        return self.store.get_project(project_id)

    def inspect(self, project_id: str | None = None) -> dict[str, object]:
        project = self._resolve_project(project_id)
        facts = self.inspector.inspect(str(project["root_path"]))
        return {
            "project_id": project["id"],
            "project_name": project["name"],
            "source_kind": project["source_kind"],
            **facts,
        }

    def context(
        self,
        *,
        task: TaskIntent,
        capabilities: dict[str, dict[str, object]],
        project_id: str | None = None,
    ) -> dict[str, object]:
        project = self._resolve_project(project_id)
        inspection = self.inspector.inspect(str(project["root_path"]))
        return self.context_builder.build(
            project=project,
            inspection=inspection,
            capabilities=capabilities,
            task=task,
        ).as_dict()
