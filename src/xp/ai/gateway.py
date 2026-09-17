from __future__ import annotations

from collections.abc import Mapping

from .contracts import (
    AIGatewayError,
    AIReadiness,
    AIRequest,
    AIResponse,
    AITransport,
)
from .settings import AISettings, AISettingsError
from .transports.openai_compatible import OpenAICompatibleTransport


class AIGateway:
    """Route-dispatch boundary for XP AI transports."""

    def __init__(
        self,
        settings: AISettings,
        transports: Mapping[str, AITransport] | None = None,
    ):
        self._settings = settings
        self._transports: dict[str, AITransport] = (
            {"openai-compatible": OpenAICompatibleTransport()}
            if transports is None
            else dict(transports)
        )

    def route(self, route_id: str | None = None):
        try:
            return self._settings.route(route_id)
        except AISettingsError as exc:
            raise AIGatewayError(str(exc)) from None

    def _transport_for(self, route):
        transport = self._transports.get(route.transport)
        if transport is None:
            raise AIGatewayError(
                f"Unknown AI transport: {route.transport}"
            )
        return transport

    def readiness(
        self,
        route_id: str | None = None,
    ) -> AIReadiness:
        route = self.route(route_id)
        transport = self._transport_for(route)
        return transport.readiness(route)

    def complete(
        self,
        request: AIRequest,
        route_id: str | None = None,
    ) -> AIResponse:
        route = self.route(route_id)
        transport = self._transport_for(route)
        return transport.complete(route, request)
