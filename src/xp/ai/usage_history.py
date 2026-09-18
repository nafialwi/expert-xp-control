from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

from xp.paths import ai_state_root


TECHNICAL_RESULTS = frozenset({"completed", "failed", "needs_attention"})


class UsageHistoryError(RuntimeError):
    """Raised when persisted AF-04 usage history is invalid."""


@dataclass(frozen=True)
class AIUsageObservation:
    record_id: str
    timestamp: datetime
    job_id: str | None
    route_id: str
    transport: str
    configured_model: str
    served_model: str | None
    cost_class: str
    latency_ms: float
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    technical_result: str
    error_type: str | None = None

    def __post_init__(self) -> None:
        if not self.record_id:
            raise ValueError("record_id must be non-empty")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        if not self.route_id:
            raise ValueError("route_id must be non-empty")
        if not self.transport:
            raise ValueError("transport must be non-empty")
        if not self.configured_model:
            raise ValueError("configured_model must be non-empty")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must not be negative")
        if self.technical_result not in TECHNICAL_RESULTS:
            raise ValueError("invalid technical_result")
        for value in (self.input_tokens, self.output_tokens, self.total_tokens):
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("token counts must be non-negative integers or None")


class UsageHistoryStore:
    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()

    @classmethod
    def for_home(cls, home: Path) -> "UsageHistoryStore":
        return cls(ai_state_root(home) / "usage-history")

    def _path_for(self, record_id: str) -> Path:
        if not isinstance(record_id, str) or not record_id:
            raise ValueError("record_id must be a non-empty string")
        digest = hashlib.sha256(record_id.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    def record(self, observation: AIUsageObservation) -> None:
        path = self._path_for(observation.record_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(observation)
        payload["timestamp"] = observation.timestamp.isoformat()
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        try:
            temp.write_text(encoded, encoding="utf-8")
            temp.replace(path)
        except OSError as exc:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            raise UsageHistoryError("Unable to persist AI usage history") from exc

    def _read_one(self, path: Path) -> AIUsageObservation:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise UsageHistoryError("Unable to read AI usage history") from exc
        if not isinstance(raw, Mapping):
            raise UsageHistoryError("Persisted AI usage record must be an object")
        try:
            observation = AIUsageObservation(
                record_id=str(raw["record_id"]),
                timestamp=datetime.fromisoformat(str(raw["timestamp"])),
                job_id=None if raw.get("job_id") is None else str(raw.get("job_id")),
                route_id=str(raw["route_id"]),
                transport=str(raw["transport"]),
                configured_model=str(raw["configured_model"]),
                served_model=None if raw.get("served_model") is None else str(raw.get("served_model")),
                cost_class=str(raw["cost_class"]),
                latency_ms=float(raw["latency_ms"]),
                input_tokens=raw.get("input_tokens"),
                output_tokens=raw.get("output_tokens"),
                total_tokens=raw.get("total_tokens"),
                technical_result=str(raw["technical_result"]),
                error_type=None if raw.get("error_type") is None else str(raw.get("error_type")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise UsageHistoryError("Persisted AI usage record is invalid") from exc
        if path.name != self._path_for(observation.record_id).name:
            raise UsageHistoryError("Persisted AI usage record id mismatch")
        return observation

    def list(self) -> tuple[AIUsageObservation, ...]:
        if not self.root.exists():
            return ()
        records = [self._read_one(path) for path in self.root.glob("*.json")]
        records.sort(key=lambda item: (item.timestamp, item.record_id))
        return tuple(records)
