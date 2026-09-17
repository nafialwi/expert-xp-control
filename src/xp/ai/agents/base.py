from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentReadiness:
    ready: bool
    status: str
    detail: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentRunRequest:
    prompt: str
    cwd: Path | None = None


@dataclass(frozen=True)
class AgentRunResult:
    status: str
    output: str
    returncode: int | None = None


class AgentRuntime(ABC):
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def readiness(self) -> AgentReadiness:
        raise NotImplementedError

    @abstractmethod
    def run(self, request: AgentRunRequest) -> AgentRunResult:
        raise NotImplementedError
