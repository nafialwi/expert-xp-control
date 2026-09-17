from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from abc import ABC, abstractmethod
from ...activity import (
    ActivityCategory,
    ActivityEvent,
    ActivityStatus,
    Provenance,
)
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



class ObservedAgentRuntime(AgentRuntime):
    """Observable wrapper around any provider-neutral AgentRuntime.

    Prompts and raw output are deliberately excluded from events.
    """

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        activity_recorder,
        activity_job_id: str,
        now=None,
    ) -> None:
        if not activity_job_id:
            raise ValueError(
                "activity_job_id must not be empty"
            )

        self._runtime = runtime
        self._activity_recorder = activity_recorder
        self._activity_job_id = activity_job_id
        self._now = now or (
            lambda: datetime.now(timezone.utc)
        )

    @property
    def name(self):
        return self._runtime.name

    def readiness(self):
        return self._runtime.readiness()

    def run(self, request):
        try:
            result = self._runtime.run(request)
        except Exception as exc:
            self._activity_recorder.record(
                ActivityEvent(
                    event_id=uuid4().hex,
                    job_id=self._activity_job_id,
                    timestamp=self._now(),
                    category=ActivityCategory.AGENT,
                    action="Agent execution",
                    provenance=Provenance(
                        source="agent-runtime",
                        processor=self.name,
                        via="agent-runtime",
                        live=False,
                    ),
                    status=ActivityStatus.FAILED,
                    result_summary=(
                        f"{type(exc).__name__}: "
                        "agent execution failed"
                    ),
                    metadata={
                        "runtime": self.name,
                    },
                )
            )
            raise

        status_text = str(result.status).upper()

        if (
            result.returncode is not None
            and result.returncode != 0
        ):
            activity_status = ActivityStatus.FAILED
        elif status_text in {
            "FAILED",
            "ERROR",
            "NOT_READY",
        }:
            activity_status = ActivityStatus.FAILED
        elif status_text in {
            "WARNING",
            "PARTIAL",
            "NEEDS_ATTENTION",
        }:
            activity_status = (
                ActivityStatus.NEEDS_ATTENTION
            )
        else:
            activity_status = ActivityStatus.COMPLETED

        self._activity_recorder.record(
            ActivityEvent(
                event_id=uuid4().hex,
                job_id=self._activity_job_id,
                timestamp=self._now(),
                category=ActivityCategory.AGENT,
                action="Agent execution",
                provenance=Provenance(
                    source="agent-runtime",
                    processor=self.name,
                    via="agent-runtime",
                    live=False,
                ),
                status=activity_status,
                result_summary=(
                    "Agent execution completed"
                    if activity_status
                    is ActivityStatus.COMPLETED
                    else "Agent execution requires attention"
                ),
                metadata={
                    "runtime": self.name,
                    "returncode": result.returncode,
                    "agent_status": result.status,
                },
            )
        )

        return result
