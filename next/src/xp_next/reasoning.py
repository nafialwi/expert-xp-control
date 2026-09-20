from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import json

from .task_contract import TaskIntent


class ReasoningContractError(ValueError):
    pass


class ReasoningStatus(str, Enum):
    COMPLETED = "COMPLETED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


@dataclass(frozen=True)
class ReasoningRequest:
    task: TaskIntent
    context: dict[str, object]
    max_tokens: int = 128

    def __post_init__(self) -> None:
        if self.task.risk != "read":
            raise ReasoningContractError("CP-04A reasoning accepts read-only tasks only")
        if self.task.mutation_allowed:
            raise ReasoningContractError("mutation is not allowed")
        if self.task.network_allowed:
            raise ReasoningContractError("task network access is not allowed")
        if bool(self.context.get("network_used")):
            raise ReasoningContractError("context must be built without network use")
        if not (16 <= self.max_tokens <= 512):
            raise ReasoningContractError("max_tokens must be between 16 and 512")
        encoded = json.dumps(self.context, ensure_ascii=False, sort_keys=True)
        if len(encoded) > 20000:
            raise ReasoningContractError("context exceeds CP-04A bounded size")

    def as_dict(self) -> dict[str, object]:
        return {
            "task": self.task.as_dict(),
            "context": self.context,
            "max_tokens": self.max_tokens,
        }


def compact_reasoning_context(context: dict[str, object]) -> dict[str, object]:
    """Remove runtime-path noise while preserving bounded reasoning semantics."""
    project = dict(context.get("project", {}))
    observed = dict(context.get("observed", {}))
    inferred = dict(context.get("inferred", {}))
    capabilities = dict(context.get("capabilities", {}))

    compact_capabilities: dict[str, dict[str, object]] = {}
    for capability_id, raw in capabilities.items():
        item = dict(raw)
        compact_capabilities[str(capability_id)] = {
            "state": item.get("state"),
            "version": item.get("version"),
        }

    return {
        "project": {
            "id": project.get("id"),
            "name": project.get("name"),
            "source_kind": project.get("source_kind"),
        },
        "source_identity": dict(context.get("source_identity", {})),
        "observed": {
            "markers": dict(observed.get("markers", {})),
            "git": dict(observed.get("git", {})),
        },
        "inferred": {
            "stack_hints": list(inferred.get("stack_hints", [])),
        },
        "capabilities": compact_capabilities,
        "network_used": bool(context.get("network_used")),
    }


@dataclass(frozen=True)
class ReasoningResult:
    status: ReasoningStatus
    output: str
    backend_id: str
    model: str
    transport: str
    external_network_used: bool
    detail: str = ""

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


def verify_reasoning_result(result: ReasoningResult) -> tuple[bool, str]:
    if result.external_network_used:
        return False, "external network use is forbidden"
    if result.transport != "loopback_http":
        return False, "unexpected transport"
    if result.backend_id != "local_qwen":
        return False, "unexpected backend"
    if result.status is not ReasoningStatus.COMPLETED:
        return False, result.detail or "reasoning did not complete"
    if not result.output.strip():
        return False, "empty reasoning output"
    if len(result.output) > 20000:
        return False, "reasoning output exceeds bounded size"
    return True, "PASS"
