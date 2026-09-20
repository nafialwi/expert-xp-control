from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path


class WorkerContractError(ValueError):
    pass


class WorkerStatus(str, Enum):
    COMPLETED = "COMPLETED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


@dataclass(frozen=True)
class WorkerReadiness:
    ready: bool
    status: str
    detail: str
    backend_id: str
    model_transport: str
    containment: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WorkerRequest:
    job_id: str
    prompt: str
    workspace_root: Path
    cwd: Path
    scope: str = "isolated_workspace"
    mutation_allowed: bool = True
    apply_to_original_allowed: bool = False
    production_allowed: bool = False

    def __post_init__(self) -> None:
        if not self.job_id.strip():
            raise WorkerContractError("job_id must not be empty")
        if not self.prompt.strip():
            raise WorkerContractError("prompt must not be empty")
        if len(self.prompt) > 12000:
            raise WorkerContractError("prompt exceeds bounded worker size")

        root = self.workspace_root.expanduser().resolve()
        cwd = self.cwd.expanduser().resolve()
        if not root.is_dir():
            raise WorkerContractError("workspace_root must be an existing directory")
        if not cwd.is_dir():
            raise WorkerContractError("cwd must be an existing directory")
        try:
            cwd.relative_to(root)
        except ValueError as exc:
            raise WorkerContractError("cwd must be inside isolated workspace") from exc

        if self.scope != "isolated_workspace":
            raise WorkerContractError("CP-05A supports isolated_workspace only")
        if not self.mutation_allowed:
            raise WorkerContractError("CP-05A worker contract expects sandbox mutation permission")
        if self.apply_to_original_allowed:
            raise WorkerContractError("CP-05A forbids apply to original project")
        if self.production_allowed:
            raise WorkerContractError("CP-05A forbids production actions")

        object.__setattr__(self, "workspace_root", root)
        object.__setattr__(self, "cwd", cwd)


@dataclass(frozen=True)
class WorkerResult:
    status: WorkerStatus
    output: str
    returncode: int
    backend_id: str
    model_transport: str
    containment: str
    apply_to_original_performed: bool = False
    detail: str = ""

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["status"] = self.status.value
        return data
