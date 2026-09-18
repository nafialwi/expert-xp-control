from __future__ import annotations

import time
from collections.abc import Mapping
from datetime import datetime, timezone
from uuid import uuid4

from ..activity import ActivityCategory, ActivityEvent, ActivityStatus, Provenance
from ..capabilities import CapabilityRegistry
from .contracts import AIGatewayError, AIReadiness, AIRequest, AIResponse, AITransport, AIUsage
from .job_state import JobAIStateStore
from .policy import AIPolicyBlockedError, PolicyDecisionKind, ZeroCostPolicy
from .settings import AISettings, AISettingsError
from .transports.openai_compatible import OpenAICompatibleTransport
from .usage_history import AIUsageObservation, UsageHistoryStore


class AIModelMismatchPendingError(AIGatewayError):
    """Prior served-model mismatch needs acknowledgement."""


class AIGateway:
    """Route-dispatch boundary for XP AI transports."""

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
        usage_history_store: UsageHistoryStore | None = None,
        monotonic=None,
    ):
        self._settings = settings
        self._transports: dict[str, AITransport] = (
            {"openai-compatible": OpenAICompatibleTransport()} if transports is None else dict(transports)
        )
        self._activity_recorder = activity_recorder
        self._activity_job_id = activity_job_id
        self._capability_registry = capability_registry
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._policy = policy or ZeroCostPolicy()
        self._job_state_store = job_state_store
        self._usage_history_store = usage_history_store
        self._monotonic = monotonic or time.monotonic
        if self._activity_recorder is not None and not self._activity_job_id:
            raise ValueError("activity_job_id is required when activity_recorder is configured")

    def route(self, route_id: str | None = None):
        try:
            return self._settings.route(route_id)
        except AISettingsError as exc:
            raise AIGatewayError(str(exc)) from None

    def _transport_for(self, route):
        transport = self._transports.get(route.transport)
        if transport is None:
            raise AIGatewayError(f"Unknown AI transport: {route.transport}")
        return transport

    def readiness(self, route_id: str | None = None) -> AIReadiness:
        route = self.route(route_id)
        return self._transport_for(route).readiness(route)

    def live_readiness_probe(self, route_id: str | None = None):
        from ..capabilities import CapabilitySnapshot, CapabilityState, LiveProbe
        route = self.route(route_id)
        capability_id = f"ai:{route.route_id}"
        def run() -> CapabilitySnapshot:
            report = self.readiness(route.route_id)
            state = CapabilityState.AVAILABLE if report.ready else CapabilityState.NEEDS_ATTENTION
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
        return LiveProbe(capability_id=capability_id, run=run)

    def _record_ai_activity(
        self,
        *,
        route,
        status: ActivityStatus,
        result_summary: str,
        served_model: str | None,
        action: str = "AI completion",
        policy_decision: str = "ALLOW",
        usage: AIUsage | None = None,
        latency_ms: float | None = None,
    ) -> None:
        if self._activity_recorder is None:
            return
        processor = served_model or route.model
        event = ActivityEvent(
            event_id=uuid4().hex,
            job_id=self._activity_job_id,
            timestamp=self._now(),
            category=ActivityCategory.AI,
            action=action,
            provenance=Provenance(source="ai-knowledge", processor=processor, via=route.transport, live=False),
            status=status,
            result_summary=result_summary,
            metadata={
                "route_id": route.route_id,
                "model": processor,
                "transport": route.transport,
                "cost_class": route.cost_class,
                "policy_decision": policy_decision,
                "configured_model": route.model,
                "served_model": served_model,
                "latency_ms": latency_ms,
                "input_tokens": None if usage is None else usage.input_tokens,
                "output_tokens": None if usage is None else usage.output_tokens,
                "total_tokens": None if usage is None else usage.total_tokens,
            },
        )
        self._activity_recorder.record(event)

    def _record_usage_history(
        self,
        *,
        route,
        job_id: str | None,
        served_model: str | None,
        usage: AIUsage | None,
        latency_ms: float,
        technical_result: str,
        error_type: str | None,
    ) -> None:
        if self._usage_history_store is None:
            return
        self._usage_history_store.record(
            AIUsageObservation(
                record_id=uuid4().hex,
                timestamp=self._now(),
                job_id=job_id,
                route_id=route.route_id,
                transport=route.transport,
                configured_model=route.model,
                served_model=served_model,
                cost_class=route.cost_class,
                latency_ms=latency_ms,
                input_tokens=None if usage is None else usage.input_tokens,
                output_tokens=None if usage is None else usage.output_tokens,
                total_tokens=None if usage is None else usage.total_tokens,
                technical_result=technical_result,
                error_type=error_type,
            )
        )

    def _unknown_approval(self, *, route, job_id: str | None) -> bool:
        if route.cost_class != "unknown" or not job_id or self._job_state_store is None:
            return False
        return self._job_state_store.is_unknown_approved(job_id, route.route_id, route.model)

    def _pending_model_mismatch(self, *, route, job_id: str | None) -> None:
        if not job_id or self._job_state_store is None:
            return
        if not self._job_state_store.has_pending_model_mismatch(job_id):
            return
        state = self._job_state_store.get(job_id)
        pending = state.pending_model_mismatch
        served_model = None if pending is None else pending.served_model
        self._record_ai_activity(
            route=route,
            status=ActivityStatus.NEEDS_ATTENTION,
            result_summary="Previous AI response used a different served model; acknowledge the mismatch before continuing",
            served_model=served_model,
            action="AI model mismatch",
            policy_decision="ALLOW",
        )
        raise AIModelMismatchPendingError(
            "Previous AI response used a different served model; acknowledge or switch model before continuing"
        )

    def complete(self, request: AIRequest, route_id: str | None = None, *, job_id: str | None = None) -> AIResponse:
        route = self.route(route_id)
        effective_job_id = job_id or self._activity_job_id
        self._pending_model_mismatch(route=route, job_id=effective_job_id)
        decision = self._policy.evaluate(
            route,
            approved_unknown=self._unknown_approval(route=route, job_id=effective_job_id),
        )
        if decision.kind is not PolicyDecisionKind.ALLOW:
            self._record_ai_activity(
                route=route,
                status=ActivityStatus.FAILED,
                result_summary=decision.reason,
                served_model=None,
                action="AI policy",
                policy_decision=decision.kind.value,
            )
            raise AIPolicyBlockedError(decision.reason)

        transport = self._transport_for(route)
        started = self._monotonic()
        try:
            response = transport.complete(route, request)
        except Exception as exc:
            latency_ms = round(max(0.0, (self._monotonic() - started) * 1000.0), 3)
            if self._capability_registry is not None:
                self._capability_registry.record_runtime_failure(
                    f"ai:{route.route_id}",
                    f"{type(exc).__name__}: AI execution failed",
                    when=self._now(),
                )
            self._record_usage_history(
                route=route,
                job_id=effective_job_id,
                served_model=None,
                usage=None,
                latency_ms=latency_ms,
                technical_result="failed",
                error_type=type(exc).__name__,
            )
            self._record_ai_activity(
                route=route,
                status=ActivityStatus.FAILED,
                result_summary=f"{type(exc).__name__}: AI execution failed",
                served_model=None,
                policy_decision=decision.kind.value,
                usage=None,
                latency_ms=latency_ms,
            )
            raise

        latency_ms = round(max(0.0, (self._monotonic() - started) * 1000.0), 3)
        served_model = response.served_model
        mismatch = served_model is not None and served_model != route.model
        if mismatch:
            if self._job_state_store is not None and effective_job_id:
                self._job_state_store.record_model_mismatch(
                    effective_job_id,
                    route_id=route.route_id,
                    configured_model=route.model,
                    served_model=served_model,
                )
            if self._capability_registry is not None:
                self._capability_registry.record_runtime_failure(
                    f"ai:{route.route_id}",
                    "ModelMismatch: provider served a different model",
                    when=self._now(),
                )
            status = ActivityStatus.NEEDS_ATTENTION
            result_summary = "AI execution completed; served model differs from configured model"
            technical_result = "needs_attention"
        else:
            status = ActivityStatus.COMPLETED
            result_summary = "AI execution completed"
            technical_result = "completed"

        self._record_usage_history(
            route=route,
            job_id=effective_job_id,
            served_model=served_model,
            usage=response.usage,
            latency_ms=latency_ms,
            technical_result=technical_result,
            error_type=None,
        )
        self._record_ai_activity(
            route=route,
            status=status,
            result_summary=result_summary,
            served_model=served_model,
            policy_decision=decision.kind.value,
            usage=response.usage,
            latency_ms=latency_ms,
        )
        return response
