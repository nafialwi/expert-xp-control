from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from uuid import uuid4

from ..activity import (
    ActivityCategory,
    ActivityEvent,
    ActivityStatus,
    Provenance,
)
from ..capabilities import CapabilityRegistry

from .contracts import (
    AIGatewayError,
    AIReadiness,
    AIRequest,
    AIResponse,
    AITransport,
)
from .job_state import JobAIStateStore
from .policy import (
    AIPolicyBlockedError,
    PolicyDecisionKind,
    ZeroCostPolicy,
)
from .settings import AISettings, AISettingsError
from .transports.openai_compatible import OpenAICompatibleTransport


class AIGateway:
    '''Route-dispatch boundary for XP AI transports.'''

    def __init__(
        self,
        settings: AISettings,
        transports: Mapping[str, AITransport] | None = None,
        *,
        activity_recorder=None,
        activity_job_id: str | None = None,
        capability_registry: CapabilityRegistry | None = None,
        now=None,
        policy: ZeroCostPolicy | None = None,
        job_state_store: JobAIStateStore | None = None,
    ):
        self._settings = settings
        self._transports: dict[str, AITransport] = (
            {"openai-compatible": OpenAICompatibleTransport()}
            if transports is None
            else dict(transports)
        )
        self._activity_recorder = activity_recorder
        self._activity_job_id = activity_job_id
        self._capability_registry = capability_registry
        self._now = now or (
            lambda: datetime.now(timezone.utc)
        )
        self._policy = policy or ZeroCostPolicy()
        self._job_state_store = job_state_store

        if (
            self._activity_recorder is not None
            and not self._activity_job_id
        ):
            raise ValueError(
                "activity_job_id is required "
                "when activity_recorder is configured"
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

    def live_readiness_probe(
        self,
        route_id: str | None = None,
    ):
        '''Build an explicit AF-03 readiness probe for one AI route.

        This calls the existing transport readiness boundary only.
        It never sends a completion request and never changes route.
        '''

        from ..capabilities import (
            CapabilitySnapshot,
            CapabilityState,
            LiveProbe,
        )

        route = self.route(route_id)
        capability_id = f"ai:{route.route_id}"

        def run() -> CapabilitySnapshot:
            report = self.readiness(route.route_id)

            state = (
                CapabilityState.AVAILABLE
                if report.ready
                else CapabilityState.NEEDS_ATTENTION
            )

            return CapabilitySnapshot(
                capability_id=capability_id,
                state=state,
                detail=report.detail,
                metadata={
                    "route_id": route.route_id,
                    "model": route.model,
                    "transport": route.transport,
                    "readiness_status": report.status,
                },
            )

        return LiveProbe(
            capability_id=capability_id,
            run=run,
        )

    def _record_ai_activity(
        self,
        *,
        route,
        status: ActivityStatus,
        result_summary: str,
        model: str | None,
        action: str = "AI completion",
        policy_decision: str = "ALLOW",
    ) -> None:
        if self._activity_recorder is None:
            return

        processor = model or route.model

        event = ActivityEvent(
            event_id=uuid4().hex,
            job_id=self._activity_job_id,
            timestamp=self._now(),
            category=ActivityCategory.AI,
            action=action,
            provenance=Provenance(
                source="ai-knowledge",
                processor=processor,
                via=route.transport,
                live=False,
            ),
            status=status,
            result_summary=result_summary,
            metadata={
                "route_id": route.route_id,
                "model": processor,
                "transport": route.transport,
                "cost_class": route.cost_class,
                "policy_decision": policy_decision,
            },
        )

        self._activity_recorder.record(event)

    def _unknown_approval(
        self,
        *,
        route,
        job_id: str | None,
    ) -> bool:
        if route.cost_class != "unknown":
            return False
        if not job_id or self._job_state_store is None:
            return False
        return self._job_state_store.is_unknown_approved(
            job_id,
            route.route_id,
            route.model,
        )

    def complete(
        self,
        request: AIRequest,
        route_id: str | None = None,
        *,
        job_id: str | None = None,
    ) -> AIResponse:
        route = self.route(route_id)

        effective_job_id = job_id or self._activity_job_id
        approved_unknown = self._unknown_approval(
            route=route,
            job_id=effective_job_id,
        )
        decision = self._policy.evaluate(
            route,
            approved_unknown=approved_unknown,
        )

        if decision.kind is not PolicyDecisionKind.ALLOW:
            self._record_ai_activity(
                route=route,
                status=ActivityStatus.FAILED,
                result_summary=decision.reason,
                model=route.model,
                action="AI policy",
                policy_decision=decision.kind.value,
            )
            raise AIPolicyBlockedError(decision.reason)

        transport = self._transport_for(route)

        try:
            response = transport.complete(
                route,
                request,
            )
        except Exception as exc:
            if self._capability_registry is not None:
                self._capability_registry.record_runtime_failure(
                    f"ai:{route.route_id}",
                    f"{type(exc).__name__}: AI execution failed",
                    when=self._now(),
                )

            self._record_ai_activity(
                route=route,
                status=ActivityStatus.FAILED,
                result_summary=(
                    f"{type(exc).__name__}: "
                    "AI execution failed"
                ),
                model=route.model,
                policy_decision=decision.kind.value,
            )

            raise

        self._record_ai_activity(
            route=route,
            status=ActivityStatus.COMPLETED,
            result_summary="AI execution completed",
            model=response.model,
            policy_decision=decision.kind.value,
        )

        return response
