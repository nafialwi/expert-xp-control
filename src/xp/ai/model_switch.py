from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from xp.ai.job_state import JobAIStateStore


_FORBIDDEN_MARKERS = (
    "chain_of_thought",
    "scratchpad",
    "reasoning_content",
    "hidden reasoning",
)


class ModelSwitchApprovalRequired(RuntimeError):
    pass


class ModelSwitchStateError(RuntimeError):
    pass


class ObservableHandoffError(ValueError):
    pass


def _validate_observable_text(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise ObservableHandoffError(
            f"{field} values must be strings"
        )

    lowered = value.casefold()
    if any(marker in lowered for marker in _FORBIDDEN_MARKERS):
        raise ObservableHandoffError(
            f"{field} contains hidden reasoning markers"
        )

    return value


def _validate_optional_text(
    value: str | None,
    *,
    field: str,
) -> str | None:
    if value is None:
        return None
    return _validate_observable_text(value, field=field)


def _validate_text_tuple(
    values: Iterable[str],
    *,
    field: str,
) -> tuple[str, ...]:
    try:
        normalized = tuple(values)
    except TypeError as exc:
        raise ObservableHandoffError(
            f"{field} must be an iterable of strings"
        ) from exc

    return tuple(
        _validate_observable_text(value, field=field)
        for value in normalized
    )


@dataclass(frozen=True)
class ObservableModelHandoff:
    goal: str | None = None
    files: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    results: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    progress: tuple[str, ...] = ()
    next_action: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "goal",
            _validate_optional_text(
                self.goal,
                field="goal",
            ),
        )
        object.__setattr__(
            self,
            "files",
            _validate_text_tuple(
                self.files,
                field="files",
            ),
        )
        object.__setattr__(
            self,
            "decisions",
            _validate_text_tuple(
                self.decisions,
                field="decisions",
            ),
        )
        object.__setattr__(
            self,
            "results",
            _validate_text_tuple(
                self.results,
                field="results",
            ),
        )
        object.__setattr__(
            self,
            "errors",
            _validate_text_tuple(
                self.errors,
                field="errors",
            ),
        )
        object.__setattr__(
            self,
            "progress",
            _validate_text_tuple(
                self.progress,
                field="progress",
            ),
        )
        object.__setattr__(
            self,
            "next_action",
            _validate_optional_text(
                self.next_action,
                field="next_action",
            ),
        )


@dataclass(frozen=True)
class ExplicitModelSwitchResult:
    job_id: str
    previous_route_id: str
    previous_model: str
    new_route_id: str
    new_model: str
    switched_at: str
    handoff: ObservableModelHandoff


class ExplicitModelSwitchService:
    def __init__(self, store: JobAIStateStore):
        self._store = store

    @staticmethod
    def _timestamp(
        when: datetime | None,
    ) -> datetime:
        value = when or datetime.now(timezone.utc)
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "switch timestamp must be timezone-aware"
            )
        return value

    def _persist_switch(
        self,
        *,
        job_id: str,
        new_route_id: str,
        new_model: str,
        requested_timestamp: datetime | None,
        reason: str | None,
    ):
        method = self._store.switch_model
        params = inspect.signature(method).parameters

        kwargs = {
            "job_id": job_id,
            "new_route_id": new_route_id,
            "new_model": new_model,
        }

        if requested_timestamp is not None:
            if "timestamp" in params:
                kwargs["timestamp"] = requested_timestamp
            elif "when" in params:
                kwargs["when"] = requested_timestamp
            else:
                raise ModelSwitchStateError(
                    "job state switch_model cannot accept explicit timestamp"
                )

        if "reason" in params:
            kwargs["reason"] = reason

        updated = method(**kwargs)

        if not updated.switches:
            raise ModelSwitchStateError(
                "job state switch_model did not record transition"
            )

        return updated, updated.switches[-1].timestamp

    def switch(
        self,
        *,
        job_id: str,
        new_route_id: str,
        new_model: str,
        approved: bool,
        handoff: ObservableModelHandoff,
        when: datetime | None = None,
        reason: str | None = None,
    ) -> ExplicitModelSwitchResult:
        if approved is not True:
            raise ModelSwitchApprovalRequired(
                "Model switch requires explicit user approval"
            )

        if not isinstance(job_id, str) or not job_id:
            raise ValueError("job_id must be a non-empty string")
        if not isinstance(new_route_id, str) or not new_route_id:
            raise ValueError(
                "new_route_id must be a non-empty string"
            )
        if not isinstance(new_model, str) or not new_model:
            raise ValueError(
                "new_model must be a non-empty string"
            )
        if not isinstance(handoff, ObservableModelHandoff):
            raise TypeError(
                "handoff must be ObservableModelHandoff"
            )

        reason = _validate_optional_text(
            reason,
            field="reason",
        )
        requested_timestamp = (
            None if when is None else self._timestamp(when)
        )

        current = self._store.get(job_id)

        if current.completed:
            raise ModelSwitchStateError(
                "Completed job cannot switch model"
            )

        if (
            current.active_route_id is None
            or current.active_model is None
        ):
            raise ModelSwitchStateError(
                "Job has no active model to switch from"
            )

        if (
            current.active_route_id == new_route_id
            and current.active_model == new_model
        ):
            raise ModelSwitchStateError(
                "Target route and model are already active"
            )

        previous_route_id = current.active_route_id
        previous_model = current.active_model

        updated, switched_at = self._persist_switch(
            job_id=job_id,
            new_route_id=new_route_id,
            new_model=new_model,
            requested_timestamp=requested_timestamp,
            reason=reason,
        )

        if updated.job_id != job_id:
            raise ModelSwitchStateError(
                "Model switch changed job identity"
            )

        if (
            updated.active_route_id != new_route_id
            or updated.active_model != new_model
        ):
            raise ModelSwitchStateError(
                "Model switch did not activate exact target"
            )

        return ExplicitModelSwitchResult(
            job_id=job_id,
            previous_route_id=previous_route_id,
            previous_model=previous_model,
            new_route_id=new_route_id,
            new_model=new_model,
            switched_at=switched_at,
            handoff=handoff,
        )
