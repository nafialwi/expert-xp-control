from __future__ import annotations

from dataclasses import dataclass

from .base import AgentReadiness, AgentRunRequest, AgentRunResult
from .default_wiring import LocalAgentWiring


@dataclass(frozen=True)
class LiveSmokeResult:
    backend_id: str
    readiness: AgentReadiness
    inference_attempted: bool
    run_result: AgentRunResult | None

    @property
    def ready(self) -> bool:
        return self.readiness.ready


def run_guarded_live_smoke(
    wiring: LocalAgentWiring,
    *,
    allow_inference: bool = False,
    smoke_prompt: str | None = None,
) -> LiveSmokeResult:
    if not isinstance(wiring, LocalAgentWiring):
        raise TypeError("wiring must be LocalAgentWiring")

    readiness = wiring.runtime.readiness()
    if not isinstance(readiness, AgentReadiness):
        raise TypeError("runtime.readiness must return AgentReadiness")

    if not readiness.ready:
        return LiveSmokeResult(
            backend_id=wiring.backend.backend_id,
            readiness=readiness,
            inference_attempted=False,
            run_result=None,
        )

    if allow_inference is not True:
        return LiveSmokeResult(
            backend_id=wiring.backend.backend_id,
            readiness=readiness,
            inference_attempted=False,
            run_result=None,
        )

    if not isinstance(smoke_prompt, str) or not smoke_prompt.strip():
        raise ValueError(
            "smoke_prompt must be explicit when allow_inference=True"
        )

    run_result = wiring.runtime.run(
        AgentRunRequest(prompt=smoke_prompt.strip())
    )
    if not isinstance(run_result, AgentRunResult):
        raise TypeError("runtime.run must return AgentRunResult")

    return LiveSmokeResult(
        backend_id=wiring.backend.backend_id,
        readiness=readiness,
        inference_attempted=True,
        run_result=run_result,
    )


__all__ = [
    "LiveSmokeResult",
    "run_guarded_live_smoke",
]
