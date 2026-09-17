from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class AIError(RuntimeError):
    """Base error for the XP AI subsystem."""


class AISettingsError(AIError):
    """Raised when AI settings are invalid."""


class AITransportError(AIError):
    """Raised when an AI transport cannot complete a request."""


class AIGatewayError(AIError):
    """Raised when AI gateway routing fails."""


@dataclass(frozen=True)
class AIRoute:
    route_id: str
    transport: str
    base_url: str
    model: str
    secret_env: str
    cost_class: str


@dataclass(frozen=True)
class AIRequest:
    messages: tuple[dict[str, Any], ...]
    tools: tuple[dict[str, Any], ...] = ()
    stream: bool = False


@dataclass(frozen=True)
class AIUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class AIToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class AIResponse:
    route_id: str
    model: str
    text: str
    tool_calls: tuple[AIToolCall, ...]
    usage: AIUsage
    finish_reason: str | None = None


@dataclass(frozen=True)
class AIReadiness:
    ready: bool
    status: str
    detail: str
    route_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


class AITransport(ABC):
    @abstractmethod
    def capability_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def readiness(self, route: AIRoute) -> AIReadiness:
        raise NotImplementedError

    @abstractmethod
    def complete(
        self,
        route: AIRoute,
        request: AIRequest,
    ) -> AIResponse:
        raise NotImplementedError
