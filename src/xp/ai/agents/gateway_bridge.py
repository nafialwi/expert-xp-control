from __future__ import annotations

from typing import Protocol, runtime_checkable

from .base import AgentReadiness, AgentRunRequest, AgentRunResult
from .local_backends import LocalBackendBinding
from .runtime_adapter import AgentRuntimeAdapter


@runtime_checkable
class GatewayPort(Protocol):
    def readiness(self, backend: LocalBackendBinding) -> AgentReadiness:
        ...

    def complete(
        self,
        backend: LocalBackendBinding,
        request: AgentRunRequest,
    ) -> AgentRunResult:
        ...


class GatewayRuntimeBridge:
    def __init__(
        self,
        *,
        backend: LocalBackendBinding,
        gateway: GatewayPort,
    ) -> None:
        if not isinstance(backend, LocalBackendBinding):
            raise TypeError("backend must be LocalBackendBinding")
        if gateway is None:
            raise TypeError("gateway is required")
        readiness = getattr(gateway, "readiness", None)
        complete = getattr(gateway, "complete", None)
        if not callable(readiness):
            raise TypeError("gateway.readiness must be callable")
        if not callable(complete):
            raise TypeError("gateway.complete must be callable")
        self._backend = backend
        self._gateway = gateway

    @property
    def backend(self) -> LocalBackendBinding:
        return self._backend

    def build_runtime(self) -> AgentRuntimeAdapter:
        backend = self._backend
        gateway = self._gateway

        def readiness_probe() -> AgentReadiness:
            result = gateway.readiness(backend)
            if not isinstance(result, AgentReadiness):
                raise TypeError("gateway.readiness must return AgentReadiness")
            return result

        def run_handler(request: AgentRunRequest) -> AgentRunResult:
            result = gateway.complete(backend, request)
            if not isinstance(result, AgentRunResult):
                raise TypeError("gateway.complete must return AgentRunResult")
            return result

        return AgentRuntimeAdapter(
            name=f"gateway:{backend.backend_id}",
            readiness_probe=readiness_probe,
            run_handler=run_handler,
        )


def build_gateway_runtime(
    *,
    backend: LocalBackendBinding,
    gateway: GatewayPort,
) -> AgentRuntimeAdapter:
    return GatewayRuntimeBridge(
        backend=backend,
        gateway=gateway,
    ).build_runtime()


__all__ = [
    "GatewayPort",
    "GatewayRuntimeBridge",
    "build_gateway_runtime",
]
