from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


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
