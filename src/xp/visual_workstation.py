from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from xp.activity import ActivityEvent
from xp.ai.hybrid_routing import HybridMode, TaskKind
from xp.orchestration import OrchestrationRequest, OrchestrationResult


def _label(value: object, *, limit: int = 240) -> str:
    text = str(value if value is not None else "")
    text = " ".join(text.replace("\x00", " ").split())
    return text[:limit]


@dataclass(frozen=True)
class VisualActivity:
    action: str
    status: str
    summary: str
    source: str
    processor: str
    live: bool

    @classmethod
    def from_event(cls, event: ActivityEvent) -> "VisualActivity":
        return cls(
            action=_label(event.action),
            status=_label(getattr(event.status, "value", event.status)),
            summary=_label(event.result_summary),
            source=_label(event.provenance.source),
            processor=_label(event.provenance.processor or "XP"),
            live=bool(event.provenance.live),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "status": self.status,
            "summary": self.summary,
            "source": self.source,
            "processor": self.processor,
            "live": self.live,
        }


@dataclass(frozen=True)
class VisualWorkstationSnapshot:
    project: str
    checkpoint: str
    recovery_status: str
    mode: str
    provider: str
    model: str
    cost_state: str
    worker: str
    permission: str
    approval: str
    verification: str
    rollback: str
    final_status: str
    live: bool = False
    activities: tuple[VisualActivity, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "xp.visual-workstation.v1",
            "project": self.project,
            "checkpoint": self.checkpoint,
            "recovery_status": self.recovery_status,
            "mode": self.mode,
            "provider": self.provider,
            "model": self.model,
            "cost_state": self.cost_state,
            "worker": self.worker,
            "permission": self.permission,
            "approval": self.approval,
            "verification": self.verification,
            "rollback": self.rollback,
            "final_status": self.final_status,
            "live": self.live,
            "activities": [item.to_dict() for item in self.activities],
        }

    @classmethod
    def idle(cls) -> "VisualWorkstationSnapshot":
        return cls(
            project="Belum dipilih",
            checkpoint="-",
            recovery_status="BELUM_DIPERIKSA",
            mode="OFFLINE",
            provider="NONE",
            model="NONE",
            cost_state="ZERO_COST_POLICY",
            worker="NONE",
            permission="READ_ONLY",
            approval="NOT_REQUIRED",
            verification="NOT_CHECKED",
            rollback="NOT_REQUIRED",
            final_status="IDLE",
            live=False,
            activities=(),
        )


def snapshot_from_orchestration(
    request: OrchestrationRequest,
    result: OrchestrationResult,
    events: Iterable[ActivityEvent] = (),
) -> VisualWorkstationSnapshot:
    selected = None
    for candidate in request.candidates:
        if candidate.candidate_id == request.selected_candidate_id:
            selected = candidate
            break

    cost_state = (
        _label(selected.cost_class).upper()
        if selected is not None
        else "N/A"
    )
    worker = (
        _label(result.route.candidate_id or "NONE")
        if result.route.execution == "worker"
        else "NONE"
    )
    if request.task_kind is TaskKind.CODE_MUTATION:
        permission = (
            "GRANTED"
            if selected is not None
            and bool(getattr(selected, "permission_granted", False))
            else "DENIED"
        )
        approval = "APPROVED" if request.approval_granted else "REQUIRED"
    else:
        permission = "READ_ONLY"
        approval = "NOT_REQUIRED"

    verification = (
        "PASS" if result.verification.passed else "PERLU_PERHATIAN"
    )
    recovery_status = (
        "READY" if result.recovery_id else "NOT_REQUIRED"
    )
    rollback = (
        "PERFORMED" if result.rollback_performed else "NOT_PERFORMED"
    )

    projected = tuple(
        VisualActivity.from_event(event)
        for event in list(events)[-50:]
    )

    return VisualWorkstationSnapshot(
        project=_label(request.project.name),
        checkpoint=_label(result.final_checkpoint),
        recovery_status=recovery_status,
        mode=_label(getattr(request.mode, "value", request.mode)).upper(),
        provider=_label(result.route.provider or "NONE"),
        model=_label(result.route.model or "NONE"),
        cost_state=cost_state,
        worker=worker,
        permission=permission,
        approval=approval,
        verification=verification,
        rollback=rollback,
        final_status=_label(
            getattr(result.status, "value", result.status)
        ).upper(),
        live=bool(result.route.live),
        activities=projected,
    )


class SnapshotStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def write(self, snapshot: VisualWorkstationSnapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(
                snapshot.to_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def read(self) -> VisualWorkstationSnapshot:
        if not self.path.is_file():
            return VisualWorkstationSnapshot.idle()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("schema") != "xp.visual-workstation.v1":
            raise ValueError("unsupported visual workstation schema")
        activities = tuple(
            VisualActivity(
                action=_label(item.get("action", "")),
                status=_label(item.get("status", "")),
                summary=_label(item.get("summary", "")),
                source=_label(item.get("source", "")),
                processor=_label(item.get("processor", "")),
                live=bool(item.get("live", False)),
            )
            for item in data.get("activities", [])
            if isinstance(item, dict)
        )
        return VisualWorkstationSnapshot(
            project=_label(data.get("project", "")),
            checkpoint=_label(data.get("checkpoint", "")),
            recovery_status=_label(data.get("recovery_status", "")),
            mode=_label(data.get("mode", "")),
            provider=_label(data.get("provider", "")),
            model=_label(data.get("model", "")),
            cost_state=_label(data.get("cost_state", "")),
            worker=_label(data.get("worker", "")),
            permission=_label(data.get("permission", "")),
            approval=_label(data.get("approval", "")),
            verification=_label(data.get("verification", "")),
            rollback=_label(data.get("rollback", "")),
            final_status=_label(data.get("final_status", "")),
            live=bool(data.get("live", False)),
            activities=activities,
        )


def render_terminal(snapshot: VisualWorkstationSnapshot) -> str:
    rows = (
        ("Project", snapshot.project),
        ("Checkpoint", snapshot.checkpoint),
        ("Recovery", snapshot.recovery_status),
        ("Mode", snapshot.mode),
        ("Provider", snapshot.provider),
        ("Model", snapshot.model),
        ("Cost", snapshot.cost_state),
        ("Worker", snapshot.worker),
        ("Permission", snapshot.permission),
        ("Approval", snapshot.approval),
        ("Verification", snapshot.verification),
        ("Rollback", snapshot.rollback),
        ("Status", snapshot.final_status),
        ("Source", "LIVE" if snapshot.live else "LOCAL/OFFLINE"),
    )
    width = max(len(key) for key, _ in rows)
    return "\n".join(f"{key:<{width}} : {value}" for key, value in rows)


__all__ = [
    "SnapshotStore",
    "VisualActivity",
    "VisualWorkstationSnapshot",
    "render_terminal",
    "snapshot_from_orchestration",
]
