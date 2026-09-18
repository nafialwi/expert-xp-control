from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from ..gateway import AIGateway
from .base import AgentReadiness, AgentRunRequest, AgentRunResult
from .local_backends import LocalBackendBinding

ReadinessDecoder = Callable[[Any], AgentReadiness]
RequestEncoder = Callable[[LocalBackendBinding, AgentRunRequest], Any]
ResponseDecoder = Callable[[Any], AgentRunResult]


class AIGatewayPortAdapter:
    def __init__(
        self,
        *,
        gateway: AIGateway,
        route_by_backend: Mapping[str, str],
        readiness_decoder: ReadinessDecoder,
        request_encoder: RequestEncoder,
        response_decoder: ResponseDecoder,
    ) -> None:
        if gateway is None:
            raise TypeError("gateway is required")
        if not isinstance(route_by_backend, Mapping) or not route_by_backend:
            raise ValueError("route_by_backend must be a non-empty mapping")
        if not callable(readiness_decoder):
            raise TypeError("readiness_decoder must be callable")
        if not callable(request_encoder):
            raise TypeError("request_encoder must be callable")
        if not callable(response_decoder):
            raise TypeError("response_decoder must be callable")

        normalized: dict[str, str] = {}
        for backend_id, route in route_by_backend.items():
            if not isinstance(backend_id, str) or not backend_id.strip():
                raise ValueError("backend id must be a non-empty string")
            if not isinstance(route, str) or not route.strip():
                raise ValueError("gateway route must be a non-empty string")
            normalized[backend_id.strip()] = route.strip()

        self._gateway = gateway
        self._route_by_backend = MappingProxyType(normalized)
        self._readiness_decoder = readiness_decoder
        self._request_encoder = request_encoder
        self._response_decoder = response_decoder

    @property
    def route_by_backend(self) -> Mapping[str, str]:
        return self._route_by_backend

    def _route_for(self, backend: LocalBackendBinding) -> str:
        if not isinstance(backend, LocalBackendBinding):
            raise TypeError("backend must be LocalBackendBinding")
        try:
            return self._route_by_backend[backend.backend_id]
        except KeyError as exc:
            raise KeyError(
                f"no explicit AIGateway route for backend: {backend.backend_id}"
            ) from exc

    def readiness(self, backend: LocalBackendBinding) -> AgentReadiness:
        route = self._route_for(backend)
        raw = self._gateway.readiness(route_id=route)
        result = self._readiness_decoder(raw)
        if not isinstance(result, AgentReadiness):
            raise TypeError("readiness_decoder must return AgentReadiness")
        return result

    def complete(
        self,
        backend: LocalBackendBinding,
        request: AgentRunRequest,
    ) -> AgentRunResult:
        if not isinstance(request, AgentRunRequest):
            raise TypeError("request must be AgentRunRequest")
        route = self._route_for(backend)
        encoded = self._request_encoder(backend, request)
        raw = self._gateway.complete(
            request=encoded,
            route_id=route,
        )
        result = self._response_decoder(raw)
        if not isinstance(result, AgentRunResult):
            raise TypeError("response_decoder must return AgentRunResult")
        return result


__all__ = [
    "AIGatewayPortAdapter",
    "ReadinessDecoder",
    "RequestEncoder",
    "ResponseDecoder",
]
