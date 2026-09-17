"""Persistent observable activity trail for XP+ AF-03.

Only observable actions, provenance and outcomes belong here.
Hidden reasoning, scratchpads and secret values must never be persisted.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class ActivityStoreError(RuntimeError):
    pass


class ActivityStatus(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_ATTENTION = "needs_attention"


class ActivityCategory(str, Enum):
    LOCAL = "local"
    PROJECT = "project"
    FILE = "file"
    GIT = "git"
    GITHUB = "github"
    LIVE_WEB = "live_web"
    AI = "ai"
    TOOL = "tool"
    AGENT = "agent"
    TEST = "test"
    USER = "user"
    SYSTEM = "system"


@dataclass(frozen=True)
class Provenance:
    source: str | None = None
    processor: str | None = None
    via: str | None = None
    live: bool = False


@dataclass(frozen=True)
class ActivityEvent:
    event_id: str
    job_id: str
    timestamp: datetime
    category: ActivityCategory
    action: str
    provenance: Provenance
    status: ActivityStatus
    result_summary: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id must not be empty")

        if not self.job_id.strip():
            raise ValueError("job_id must not be empty")

        if not self.action.strip():
            raise ValueError("action must not be empty")

        if (
            self.timestamp.tzinfo is None
            or self.timestamp.utcoffset() is None
        ):
            raise ValueError(
                "timestamp must be timezone-aware"
            )


_DROP_KEYS = {
    "chain_of_thought",
    "scratchpad",
    "reasoning_content",
}

_SECRET_KEY_FRAGMENTS = (
    "authorization",
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
)


def _normalized_key(key: object) -> str:
    text = str(key).strip().lower()
    return "".join(
        char if char.isalnum() else "_"
        for char in text
    ).strip("_")


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        clean: dict[str, Any] = {}

        for raw_key, raw_value in value.items():
            key = str(raw_key)
            normalized = _normalized_key(key)

            if normalized in _DROP_KEYS:
                continue

            if any(
                fragment in normalized
                for fragment in _SECRET_KEY_FRAGMENTS
            ):
                clean[key] = "[REDACTED]"
                continue

            clean[key] = _sanitize(raw_value)

        return clean

    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]

    if isinstance(value, list):
        return [_sanitize(item) for item in value]

    if isinstance(value, (str, int, float, bool)):
        return value

    if value is None:
        return None

    return str(value)


def _event_to_dict(event: ActivityEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "job_id": event.job_id,
        "timestamp": event.timestamp.isoformat(),
        "category": event.category.value,
        "action": event.action,
        "provenance": {
            "source": event.provenance.source,
            "processor": event.provenance.processor,
            "via": event.provenance.via,
            "live": event.provenance.live,
        },
        "status": event.status.value,
        "result_summary": event.result_summary,
        "metadata": _sanitize(event.metadata),
    }


def _event_from_dict(data: Mapping[str, Any]) -> ActivityEvent:
    provenance_data = data.get("provenance")

    if not isinstance(provenance_data, Mapping):
        raise ActivityStoreError(
            "activity record provenance is invalid"
        )

    metadata = data.get("metadata", {})

    if not isinstance(metadata, Mapping):
        raise ActivityStoreError(
            "activity record metadata is invalid"
        )

    try:
        timestamp = datetime.fromisoformat(
            str(data["timestamp"])
        )

        return ActivityEvent(
            event_id=str(data["event_id"]),
            job_id=str(data["job_id"]),
            timestamp=timestamp,
            category=ActivityCategory(
                str(data["category"])
            ),
            action=str(data["action"]),
            provenance=Provenance(
                source=provenance_data.get("source"),
                processor=provenance_data.get(
                    "processor"
                ),
                via=provenance_data.get("via"),
                live=bool(
                    provenance_data.get("live", False)
                ),
            ),
            status=ActivityStatus(
                str(data["status"])
            ),
            result_summary=str(
                data["result_summary"]
            ),
            metadata=dict(metadata),
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise ActivityStoreError(
            "activity record is invalid"
        ) from exc


class ActivityStore:
    def __init__(self, root: Path):
        self.root = Path(root).expanduser()

    @classmethod
    def for_home(cls, home: Path) -> "ActivityStore":
        from .paths import XPPaths

        return cls(XPPaths.from_home(home).activity)

    def _path_for_job(self, job_id: str) -> Path:
        digest = hashlib.sha256(
            job_id.encode("utf-8")
        ).hexdigest()

        return self.root / f"{digest}.jsonl"

    def append(self, event: ActivityEvent) -> None:
        self.root.mkdir(
            parents=True,
            exist_ok=True,
        )

        path = self._path_for_job(event.job_id)

        payload = json.dumps(
            _event_to_dict(event),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        with path.open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(payload)
            handle.write("\n")

    def list_for_job(
        self,
        job_id: str,
    ) -> tuple[ActivityEvent, ...]:
        path = self._path_for_job(job_id)

        if not path.exists():
            return ()

        events: list[ActivityEvent] = []

        try:
            with path.open(
                "r",
                encoding="utf-8",
            ) as handle:
                for line_number, line in enumerate(
                    handle,
                    start=1,
                ):
                    if not line.strip():
                        continue

                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ActivityStoreError(
                            "malformed activity record "
                            f"at line {line_number}"
                        ) from exc

                    if not isinstance(data, Mapping):
                        raise ActivityStoreError(
                            "activity record must be "
                            f"an object at line {line_number}"
                        )

                    item = _event_from_dict(data)

                    if item.job_id != job_id:
                        raise ActivityStoreError(
                            "activity job identity mismatch "
                            f"at line {line_number}"
                        )

                    events.append(item)

        except OSError as exc:
            raise ActivityStoreError(
                f"unable to read activity history: {exc}"
            ) from exc

        return tuple(events)


def _objective_count(
    name: str,
    value: int,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ValueError(
            f"{name} must be a non-negative integer"
        )

    return value


def test_result_metadata(
    *,
    passed: int,
    failed: int,
    skipped: int = 0,
) -> dict[str, int]:
    """Return already-known objective test counts.

    This helper never parses logs or model reasoning.
    """

    return {
        "passed": _objective_count(
            "passed",
            passed,
        ),
        "failed": _objective_count(
            "failed",
            failed,
        ),
        "skipped": _objective_count(
            "skipped",
            skipped,
        ),
    }


def source_result_metadata(
    *,
    source_count: int,
) -> dict[str, int]:
    """Return an already-known objective source count."""

    return {
        "source_count": _objective_count(
            "source_count",
            source_count,
        ),
    }
