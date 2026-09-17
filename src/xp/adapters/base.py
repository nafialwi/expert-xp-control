from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..capabilities import CapabilitySnapshot, CapabilityState


class AdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdapterReadiness:
    """Non-mutating readiness result shared by XP+ capability adapters."""

    ready: bool
    status: str  # READY | READY_WITH_LIMITATIONS | NOT_READY
    detail: str
    capabilities: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


_ADAPTER_STATE_MAP = {
    "READY": CapabilityState.AVAILABLE,
    "READY_WITH_LIMITATIONS": CapabilityState.NEEDS_ATTENTION,
    "NOT_READY": CapabilityState.UNAVAILABLE,
}


def adapter_readiness_to_capability_snapshots(
    report: AdapterReadiness,
    *,
    checked_at: datetime | None = None,
) -> tuple[CapabilitySnapshot, ...]:
    """Map existing local adapter readiness into AF-03 canonical state."""

    try:
        state = _ADAPTER_STATE_MAP[report.status]
    except KeyError as exc:
        raise ValueError(
            f"unsupported adapter readiness status: {report.status}"
        ) from exc

    metadata = {
        "adapter_ready": report.ready,
        "adapter_status": report.status,
        **dict(report.metadata),
    }

    return tuple(
        CapabilitySnapshot(
            capability_id=capability_id,
            state=state,
            detail=report.detail,
            checked_at=checked_at,
            live=False,
            metadata=dict(metadata),
        )
        for capability_id in sorted(report.capabilities)
    )


class CapabilityAdapter(ABC):
    @abstractmethod
    def capabilities(self) -> set[str]:
        raise NotImplementedError

    def readiness(self) -> AdapterReadiness:
        caps = tuple(sorted(self.capabilities()))
        return AdapterReadiness(
            ready=True,
            status="READY",
            detail="Adapter loaded.",
            capabilities=caps,
        )

    def capability_snapshots(
        self,
        *,
        checked_at: datetime | None = None,
    ) -> tuple[CapabilitySnapshot, ...]:
        return adapter_readiness_to_capability_snapshots(
            self.readiness(),
            checked_at=checked_at,
        )
