from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from urllib.parse import urlparse

from .runtime_adapter import AgentRuntimeAdapter, ReadinessProbe, RunHandler


@dataclass(frozen=True)
class LocalBackendBinding:
    backend_id: str
    display_name: str
    api_base_url: str
    readiness_url: str
    transport: str = "openai-compatible"
    policy_classification: str = "policy-controlled"

    def __post_init__(self) -> None:
        for label, value in (
            ("backend_id", self.backend_id),
            ("display_name", self.display_name),
            ("api_base_url", self.api_base_url),
            ("readiness_url", self.readiness_url),
            ("transport", self.transport),
            ("policy_classification", self.policy_classification),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} must be a non-empty string")

        for label, value in (
            ("api_base_url", self.api_base_url),
            ("readiness_url", self.readiness_url),
        ):
            parsed = urlparse(value)
            if parsed.scheme != "http":
                raise ValueError(f"{label} must use http loopback")
            if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError(f"{label} must use a loopback host")

    @property
    def is_loopback(self) -> bool:
        return True


LOCAL_QWEN = LocalBackendBinding(
    backend_id="local-qwen",
    display_name="Local Qwen",
    api_base_url="http://127.0.0.1:8080/v1",
    readiness_url="http://127.0.0.1:8080/health",
    policy_classification="free-local",
)

ROUTER_9 = LocalBackendBinding(
    backend_id="9router",
    display_name="9Router",
    api_base_url="http://127.0.0.1:20128/v1",
    readiness_url="http://127.0.0.1:20128/v1/models",
    policy_classification="policy-controlled",
)

DEFAULT_ZERO_COST_BACKEND_ID = LOCAL_QWEN.backend_id

_LOCAL_BACKENDS = MappingProxyType(
    {
        LOCAL_QWEN.backend_id: LOCAL_QWEN,
        ROUTER_9.backend_id: ROUTER_9,
    }
)


def local_backend_ids() -> tuple[str, ...]:
    return tuple(_LOCAL_BACKENDS.keys())


def resolve_local_backend(backend_id: str) -> LocalBackendBinding:
    if not isinstance(backend_id, str) or not backend_id.strip():
        raise ValueError("backend_id must be explicit")
    normalized = backend_id.strip()
    try:
        return _LOCAL_BACKENDS[normalized]
    except KeyError as exc:
        raise KeyError(f"unknown local backend: {normalized}") from exc


def build_bound_runtime(
    backend: LocalBackendBinding,
    *,
    readiness_probe: ReadinessProbe,
    run_handler: RunHandler,
) -> AgentRuntimeAdapter:
    if not isinstance(backend, LocalBackendBinding):
        raise TypeError("backend must be LocalBackendBinding")
    return AgentRuntimeAdapter(
        name=f"backend:{backend.backend_id}",
        readiness_probe=readiness_probe,
        run_handler=run_handler,
    )


__all__ = [
    "DEFAULT_ZERO_COST_BACKEND_ID",
    "LOCAL_QWEN",
    "ROUTER_9",
    "LocalBackendBinding",
    "build_bound_runtime",
    "local_backend_ids",
    "resolve_local_backend",
]
