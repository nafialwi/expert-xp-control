from __future__ import annotations

from .aigateway_port import AIGatewayPortAdapter
from .contract_mapping import (
    decode_ai_readiness,
    decode_ai_response,
    encode_agent_request,
)
from .default_wiring import LocalAgentWiring
from .live_readiness import Clock, HTTPGet, build_live_readiness_probe
from .local_backends import (
    DEFAULT_ZERO_COST_BACKEND_ID,
    resolve_local_backend,
)
from .runtime_adapter import AgentRuntimeAdapter
from ..gateway import AIGateway


def build_live_local_agent_wiring(
    *,
    gateway: AIGateway,
    backend_id: str,
    route_id: str,
    model: str,
    allow_live: bool,
    http_get: HTTPGet,
    clock: Clock,
    timeout_seconds: float = 2.5,
) -> LocalAgentWiring:
    if gateway is None:
        raise TypeError("gateway is required")
    if not isinstance(route_id, str) or not route_id.strip():
        raise ValueError("route_id must be explicit")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("model must be explicit")

    backend = resolve_local_backend(backend_id)
    route = route_id.strip()
    selected_model = model.strip()

    live_probe = build_live_readiness_probe(
        backend=backend,
        allow_live=allow_live,
        http_get=http_get,
        clock=clock,
        timeout_seconds=timeout_seconds,
    )

    port = AIGatewayPortAdapter(
        gateway=gateway,
        route_by_backend={backend.backend_id: route},
        readiness_decoder=decode_ai_readiness,
        request_encoder=lambda selected_backend, request: encode_agent_request(
            request,
            model=selected_model,
        ),
        response_decoder=decode_ai_response,
    )

    runtime = AgentRuntimeAdapter(
        name=f"gateway:{backend.backend_id}",
        readiness_probe=live_probe,
        run_handler=lambda request: port.complete(backend, request),
    )

    return LocalAgentWiring(
        backend=backend,
        route_id=route,
        model=selected_model,
        runtime=runtime,
    )


def build_default_zero_cost_live_wiring(
    *,
    gateway: AIGateway,
    route_id: str,
    model: str,
    allow_live: bool,
    http_get: HTTPGet,
    clock: Clock,
    timeout_seconds: float = 2.5,
) -> LocalAgentWiring:
    return build_live_local_agent_wiring(
        gateway=gateway,
        backend_id=DEFAULT_ZERO_COST_BACKEND_ID,
        route_id=route_id,
        model=model,
        allow_live=allow_live,
        http_get=http_get,
        clock=clock,
        timeout_seconds=timeout_seconds,
    )


__all__ = [
    "build_default_zero_cost_live_wiring",
    "build_live_local_agent_wiring",
]
