from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from .task_contract import TaskIntent


@dataclass(frozen=True)
class ProjectContext:
    project: dict[str, object]
    source_identity: dict[str, object]
    observed: dict[str, object]
    inferred: dict[str, object]
    capabilities: dict[str, dict[str, object]]
    task: dict[str, object]
    network_used: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "project": deepcopy(self.project),
            "source_identity": deepcopy(self.source_identity),
            "observed": deepcopy(self.observed),
            "inferred": deepcopy(self.inferred),
            "capabilities": deepcopy(self.capabilities),
            "task": deepcopy(self.task),
            "network_used": self.network_used,
        }


class ProjectContextBuilder:
    """Compose bounded project context without reasoning or mutation."""

    def build(
        self,
        *,
        project: dict[str, object],
        inspection: dict[str, object],
        capabilities: dict[str, dict[str, object]],
        task: TaskIntent,
    ) -> ProjectContext:
        project_view = {
            "id": project["id"],
            "name": project["name"],
            "root_path": project["root_path"],
            "source_kind": project["source_kind"],
        }

        markers = deepcopy(dict(inspection.get("markers", {})))
        git = deepcopy(dict(inspection.get("git", {})))
        observed = {
            "root": inspection.get("root"),
            "markers": markers,
            "git": git,
        }
        inferred = {
            "stack_hints": list(inspection.get("stack_hints", [])),
        }

        if project["source_kind"] == "git" and git.get("inside_work_tree") is True:
            source_identity = {
                "kind": "git",
                "branch": git.get("branch"),
                "head": git.get("head"),
                "dirty": git.get("dirty"),
            }
        else:
            source_identity = {
                "kind": project["source_kind"],
                "root": inspection.get("root"),
            }

        capability_network = any(
            bool(item.get("network_used"))
            for item in capabilities.values()
        )
        network_used = bool(inspection.get("network_used")) or capability_network

        return ProjectContext(
            project=project_view,
            source_identity=source_identity,
            observed=observed,
            inferred=inferred,
            capabilities=deepcopy(capabilities),
            task=task.as_dict(),
            network_used=network_used,
        )
