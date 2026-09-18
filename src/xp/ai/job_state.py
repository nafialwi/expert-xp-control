from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from xp.paths import ai_state_root


class JobAIStateError(RuntimeError):
    """Raised when persisted AF-04 job state is invalid."""


@dataclass(frozen=True)
class UnknownCostApproval:
    route_id: str
    model: str


@dataclass(frozen=True)
class ModelSwitch:
    previous_route_id: str
    previous_model: str
    new_route_id: str
    new_model: str
    timestamp: str
    reason: str | None = None


@dataclass(frozen=True)
class ModelMismatch:
    route_id: str
    configured_model: str
    served_model: str
    observed_at: str


@dataclass(frozen=True)
class JobAIState:
    job_id: str
    active_route_id: str | None = None
    active_model: str | None = None
    approved_unknown: UnknownCostApproval | None = None
    switches: tuple[ModelSwitch, ...] = ()
    pending_model_mismatch: ModelMismatch | None = None
    completed: bool = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobAIStateStore:
    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()

    @classmethod
    def for_home(cls, home: Path) -> "JobAIStateStore":
        return cls(ai_state_root(home))

    def _path_for(self, job_id: str) -> Path:
        if not isinstance(job_id, str) or not job_id:
            raise ValueError("job_id must be a non-empty string")
        digest = hashlib.sha256(job_id.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    def _empty(self, job_id: str) -> JobAIState:
        return JobAIState(job_id=job_id)

    def get(self, job_id: str) -> JobAIState:
        path = self._path_for(job_id)
        if not path.exists():
            return self._empty(job_id)

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise JobAIStateError(
                "Unable to read persisted AI job state"
            ) from exc

        if not isinstance(raw, Mapping):
            raise JobAIStateError(
                "Persisted AI job state must be an object"
            )

        if raw.get("job_id") != job_id:
            raise JobAIStateError(
                "Persisted AI job state job_id mismatch"
            )

        approval_raw = raw.get("approved_unknown")
        approval = None
        if approval_raw is not None:
            if not isinstance(approval_raw, Mapping):
                raise JobAIStateError(
                    "Persisted unknown-cost approval is invalid"
                )
            approval = UnknownCostApproval(
                route_id=str(approval_raw.get("route_id") or ""),
                model=str(approval_raw.get("model") or ""),
            )

        switches_raw = raw.get("switches", [])
        if not isinstance(switches_raw, list):
            raise JobAIStateError(
                "Persisted model switch history is invalid"
            )

        switches = []
        for item in switches_raw:
            if not isinstance(item, Mapping):
                raise JobAIStateError(
                    "Persisted model switch entry is invalid"
                )
            switches.append(
                ModelSwitch(
                    previous_route_id=str(
                        item.get("previous_route_id") or ""
                    ),
                    previous_model=str(
                        item.get("previous_model") or ""
                    ),
                    new_route_id=str(
                        item.get("new_route_id") or ""
                    ),
                    new_model=str(
                        item.get("new_model") or ""
                    ),
                    timestamp=str(item.get("timestamp") or ""),
                    reason=(
                        None
                        if item.get("reason") is None
                        else str(item.get("reason"))
                    ),
                )
            )

        mismatch_raw = raw.get("pending_model_mismatch")
        mismatch = None
        if mismatch_raw is not None:
            if not isinstance(mismatch_raw, Mapping):
                raise JobAIStateError("Persisted model mismatch is invalid")
            mismatch = ModelMismatch(
                route_id=str(mismatch_raw.get("route_id") or ""),
                configured_model=str(mismatch_raw.get("configured_model") or ""),
                served_model=str(mismatch_raw.get("served_model") or ""),
                observed_at=str(mismatch_raw.get("observed_at") or ""),
            )

        return JobAIState(
            job_id=job_id,
            active_route_id=(
                None
                if raw.get("active_route_id") is None
                else str(raw.get("active_route_id"))
            ),
            active_model=(
                None
                if raw.get("active_model") is None
                else str(raw.get("active_model"))
            ),
            approved_unknown=approval,
            switches=tuple(switches),
            pending_model_mismatch=mismatch,
            completed=bool(raw.get("completed", False)),
        )

    def save(self, state: JobAIState) -> None:
        path = self._path_for(state.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload: dict[str, Any] = asdict(state)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"

        temp = path.with_name(
            f".{path.name}.tmp-{os.getpid()}"
        )
        try:
            temp.write_text(encoded, encoding="utf-8")
            temp.replace(path)
        except OSError as exc:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            raise JobAIStateError(
                "Unable to persist AI job state"
            ) from exc

    def set_active_model(
        self,
        job_id: str,
        route_id: str,
        model: str,
    ) -> JobAIState:
        current = self.get(job_id)
        if current.completed:
            raise JobAIStateError(
                "Completed job cannot activate an AI model"
            )

        state = replace(
            current,
            active_route_id=route_id,
            active_model=model,
        )
        self.save(state)
        return state

    def approve_unknown(
        self,
        job_id: str,
        route_id: str,
        model: str,
    ) -> JobAIState:
        current = self.get(job_id)
        if current.completed:
            raise JobAIStateError(
                "Completed job cannot receive AI approval"
            )

        state = replace(
            current,
            approved_unknown=UnknownCostApproval(
                route_id=route_id,
                model=model,
            ),
        )
        self.save(state)
        return state

    def is_unknown_approved(
        self,
        job_id: str,
        route_id: str,
        model: str,
    ) -> bool:
        state = self.get(job_id)
        approval = state.approved_unknown
        return bool(
            not state.completed
            and approval is not None
            and approval.route_id == route_id
            and approval.model == model
        )

    def switch_model(
        self,
        job_id: str,
        *,
        new_route_id: str,
        new_model: str,
        reason: str | None = None,
    ) -> JobAIState:
        current = self.get(job_id)

        if current.completed:
            raise JobAIStateError(
                "Completed job cannot switch AI model"
            )

        if (
            current.active_route_id is None
            or current.active_model is None
        ):
            raise JobAIStateError(
                "Active AI model must be set before switching"
            )

        switch = ModelSwitch(
            previous_route_id=current.active_route_id,
            previous_model=current.active_model,
            new_route_id=new_route_id,
            new_model=new_model,
            timestamp=_now_iso(),
            reason=reason,
        )

        state = replace(
            current,
            active_route_id=new_route_id,
            active_model=new_model,
            approved_unknown=None,
            switches=current.switches + (switch,),
            pending_model_mismatch=None,
        )
        self.save(state)
        return state

    def record_model_mismatch(
        self,
        job_id: str,
        *,
        route_id: str,
        configured_model: str,
        served_model: str,
    ) -> JobAIState:
        current = self.get(job_id)
        if current.completed:
            raise JobAIStateError("Completed job cannot record model mismatch")
        state = replace(
            current,
            pending_model_mismatch=ModelMismatch(
                route_id=route_id,
                configured_model=configured_model,
                served_model=served_model,
                observed_at=_now_iso(),
            ),
        )
        self.save(state)
        return state

    def has_pending_model_mismatch(self, job_id: str) -> bool:
        state = self.get(job_id)
        return bool(not state.completed and state.pending_model_mismatch is not None)

    def acknowledge_model_mismatch(self, job_id: str) -> JobAIState:
        current = self.get(job_id)
        state = replace(current, pending_model_mismatch=None)
        self.save(state)
        return state

    def complete(self, job_id: str) -> JobAIState:
        current = self.get(job_id)
        state = replace(
            current,
            approved_unknown=None,
            pending_model_mismatch=None,
            completed=True,
        )
        self.save(state)
        return state
