from __future__ import annotations

from dataclasses import dataclass

from ..gateway import AIGateway
from .aigateway_port import AIGatewayPortAdapter
from .contract_mapping import (
    decode_ai_readiness,
    decode_ai_response,
    encode_agent_request,
)
from .gateway_bridge import build_gateway_runtime
from .local_backends import (
    DEFAULT_ZERO_COST_BACKEND_ID,
    LocalBackendBinding,
    resolve_local_backend,
)
from .runtime_adapter import AgentRuntimeAdapter


@dataclass(frozen=True)
class LocalAgentWiring:
    backend: LocalBackendBinding
    route_id: str
    model: str
    runtime: AgentRuntimeAdapter


def build_local_agent_wiring(
    *,
    gateway: AIGateway,
    backend_id: str,
    route_id: str,
    model: str,
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

    runtime = build_gateway_runtime(
        backend=backend,
        gateway=port,
    )

    return LocalAgentWiring(
        backend=backend,
        route_id=route,
        model=selected_model,
        runtime=runtime,
    )


def build_default_zero_cost_wiring(
    *,
    gateway: AIGateway,
    route_id: str,
    model: str,
) -> LocalAgentWiring:
    return build_local_agent_wiring(
        gateway=gateway,
        backend_id=DEFAULT_ZERO_COST_BACKEND_ID,
        route_id=route_id,
        model=model,
    )


__all__ = [
    "LocalAgentWiring",
    "build_default_zero_cost_wiring",
    "build_local_agent_wiring",
]
