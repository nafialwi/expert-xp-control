from __future__ import annotations

from collections.abc import Callable

from .base import AgentReadiness, AgentRunRequest, AgentRunResult, AgentRuntime

ReadinessProbe = Callable[[], AgentReadiness]
RunHandler = Callable[[AgentRunRequest], AgentRunResult]


class AgentRuntimeAdapter(AgentRuntime):
    def __init__(
        self,
        *,
        name: str,
        readiness_probe: ReadinessProbe,
        run_handler: RunHandler,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string")
        if not callable(readiness_probe):
            raise TypeError("readiness_probe must be callable")
        if not callable(run_handler):
            raise TypeError("run_handler must be callable")
        self._name = name.strip()
        self._readiness_probe = readiness_probe
        self._run_handler = run_handler

    def name(self) -> str:
        return self._name

    def readiness(self) -> AgentReadiness:
        result = self._readiness_probe()
        if not isinstance(result, AgentReadiness):
            raise TypeError("readiness_probe must return AgentReadiness")
        return result

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        if not isinstance(request, AgentRunRequest):
            raise TypeError("request must be AgentRunRequest")
        result = self._run_handler(request)
        if not isinstance(result, AgentRunResult):
            raise TypeError("run_handler must return AgentRunResult")
        return result


__all__ = ["AgentRuntimeAdapter", "ReadinessProbe", "RunHandler"]
