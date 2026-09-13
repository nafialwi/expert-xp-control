from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

STATE_VERSION = 1


class IncompatibleStateVersion(ValueError):
    pass


@dataclass
class RunState:
    project_id: str
    run_id: str
    stage: str = "IDLE"
    milestone: str | None = None
    state_version: int = STATE_VERSION
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["state_version"] = STATE_VERSION
        return value

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunState":
        version = int(data.get("state_version", 0))
        if version != STATE_VERSION:
            raise IncompatibleStateVersion(
                f"Unsupported XP state version {version}; expected {STATE_VERSION}"
            )
        return cls(
            project_id=str(data["project_id"]),
            run_id=str(data["run_id"]),
            stage=str(data.get("stage", "IDLE")),
            milestone=data.get("milestone"),
            state_version=version,
            created_at=str(data.get("created_at") or datetime.now(timezone.utc).isoformat()),
            updated_at=str(data.get("updated_at") or datetime.now(timezone.utc).isoformat()),
            metadata=dict(data.get("metadata") or {}),
        )


def read_run_state_v1(path: "Path") -> RunState:
    """Read state_version=1 without migration or rewrite."""
    import json
    from pathlib import Path

    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid XP run state: {source}") from exc
    state = RunState.from_dict(dict(data))
    if state.state_version != 1:
        raise IncompatibleStateVersion(
            f"Unsupported XP state version {state.state_version}; expected 1"
        )
    return state
