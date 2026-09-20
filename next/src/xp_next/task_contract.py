from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum


class TaskContractError(ValueError):
    pass


class TaskIntentKind(str, Enum):
    INSPECT = "INSPECT"
    ANALYZE = "ANALYZE"
    EXPLAIN = "EXPLAIN"


@dataclass(frozen=True)
class TaskIntent:
    goal: str
    kind: TaskIntentKind
    risk: str
    mutation_allowed: bool
    network_allowed: bool
    source: str = "user"

    @classmethod
    def read_only(cls, *, goal: str, kind: TaskIntentKind) -> "TaskIntent":
        clean_goal = goal.strip()
        if not clean_goal:
            raise TaskContractError("task goal must not be empty")
        if not isinstance(kind, TaskIntentKind):
            raise TaskContractError("kind must be a TaskIntentKind")
        return cls(
            goal=clean_goal,
            kind=kind,
            risk="read",
            mutation_allowed=False,
            network_allowed=False,
            source="user",
        )

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["kind"] = self.kind.value
        return data
