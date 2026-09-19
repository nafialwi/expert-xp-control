from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from xp.activity import Provenance
from xp.capabilities import CapabilityState


class HybridMode(str, Enum):
    OFFLINE = "offline"
    ANALYSIS = "analysis"
    WORKER = "worker"
    LIVE = "live"


class TaskKind(str, Enum):
    DETERMINISTIC = "deterministic"
    SOURCE_ANALYSIS = "source_analysis"
    PRIVATE_SIMPLE = "private_simple"
    CODE_MUTATION = "code_mutation"
    LIVE_RESEARCH = "live_research"


class CandidateKind(str, Enum):
    AI = "ai"
    WORKER = "worker"


class RouteLocality(str, Enum):
    LOCAL = "local"
    LOOPBACK = "loopback"
    CLOUD = "cloud"


class QuotaState(str, Enum):
    OK = "ok"
    LOW = "low"
    EXHAUSTED = "exhausted"
    UNKNOWN = "unknown"


class LatencyClass(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class RoutingStatus(str, Enum):
    DETERMINISTIC = "deterministic"
    SELECTED = "selected"
    USER_CHOICE_REQUIRED = "user_choice_required"
    BLOCKED = "blocked"
    NEEDS_ATTENTION = "needs_attention"


class ProviderFailureKind(str, Enum):
    QUOTA_OR_RATE_LIMIT = "quota_or_rate_limit"
    AUTHENTICATION = "authentication"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"


@dataclass(frozen=True)
class HybridCandidate:
    candidate_id: str
    kind: CandidateKind
    provider: str
    model: str
    locality: RouteLocality
    cost_class: str
    readiness: CapabilityState
    quota: QuotaState = QuotaState.UNKNOWN
    latency: LatencyClass = LatencyClass.UNKNOWN
    supports_live: bool = False
    privacy_safe: bool = False
    permission_granted: bool = False

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must not be empty")
        if not self.provider.strip():
            raise ValueError("provider must not be empty")
        if not self.model.strip():
            raise ValueError("model must not be empty")
        if self.cost_class not in {"free", "paid", "unknown"}:
            raise ValueError("cost_class must be free, paid, or unknown")


@dataclass(frozen=True)
class HybridRoutingRequest:
    task_kind: TaskKind
    mode: HybridMode
    selected_candidate_id: str | None = None
    allow_paid: bool = False
    privacy_required: bool = False
    explicit_live: bool = False


@dataclass(frozen=True)
class HybridRoutingDecision:
    status: RoutingStatus
    execution: str
    candidate_id: str | None
    provider: str | None
    model: str | None
    live: bool
    reason: str
    alternatives_considered: tuple[str, ...] = ()

    def provenance_for(self, source: str) -> Provenance:
        processor = None
        if self.provider and self.model:
            processor = f"{self.provider}:{self.model}"
        elif self.provider:
            processor = self.provider
        return Provenance(
            source=source,
            processor=processor,
            via="hybrid_router",
            live=self.live,
        )


def classify_provider_failure(
    *,
    http_status: int | None,
    detail: str,
    timed_out: bool = False,
) -> ProviderFailureKind:
    text = detail.lower()

    if timed_out or http_status == 408 or "timeout" in text or "timed out" in text:
        return ProviderFailureKind.TIMEOUT

    quota_markers = (
        "quota",
        "rate limit",
        "rate_limit",
        "resource_exhausted",
        "too many requests",
        "429",
    )
    if http_status == 429 or any(marker in text for marker in quota_markers):
        return ProviderFailureKind.QUOTA_OR_RATE_LIMIT

    auth_markers = (
        "unauthorized",
        "forbidden",
        "invalid api key",
        "invalid_api_key",
        "authentication",
    )
    if http_status in {401, 403} or any(marker in text for marker in auth_markers):
        return ProviderFailureKind.AUTHENTICATION

    temporary_markers = (
        "temporarily unavailable",
        "service unavailable",
        "high demand",
        "overloaded",
    )
    if http_status in {502, 503, 504} or any(
        marker in text for marker in temporary_markers
    ):
        return ProviderFailureKind.TEMPORARILY_UNAVAILABLE

    return ProviderFailureKind.PROVIDER_ERROR


class HybridRouter:
    # Pure/offline routing policy.
    #
    # This class never probes network services and never executes AI/workers.
    # It only evaluates an explicit routing request against declared/observed
    # candidate state.

    def route(
        self,
        request: HybridRoutingRequest,
        candidates: Sequence[HybridCandidate],
    ) -> HybridRoutingDecision:
        if request.task_kind is TaskKind.DETERMINISTIC:
            return HybridRoutingDecision(
                status=RoutingStatus.DETERMINISTIC,
                execution="deterministic_tool",
                candidate_id=None,
                provider=None,
                model=None,
                live=False,
                reason="Deterministic task stays on deterministic tooling.",
            )

        if request.selected_candidate_id is None:
            return HybridRoutingDecision(
                status=RoutingStatus.USER_CHOICE_REQUIRED,
                execution="none",
                candidate_id=None,
                provider=None,
                model=None,
                live=False,
                reason="Explicit provider/model/worker selection is required.",
                alternatives_considered=tuple(
                    candidate.candidate_id for candidate in candidates
                ),
            )

        selected = None
        for candidate in candidates:
            if candidate.candidate_id == request.selected_candidate_id:
                selected = candidate
                break

        if selected is None:
            return HybridRoutingDecision(
                status=RoutingStatus.BLOCKED,
                execution="none",
                candidate_id=request.selected_candidate_id,
                provider=None,
                model=None,
                live=False,
                reason="Explicitly selected route does not exist.",
            )

        common = self._common_gate(request, selected)
        if common is not None:
            return common

        if request.task_kind is TaskKind.CODE_MUTATION:
            if request.mode is not HybridMode.WORKER:
                return self._blocked(
                    selected,
                    "Code/file mutation requires WORKER mode.",
                )
            if selected.kind is not CandidateKind.WORKER:
                return self._blocked(
                    selected,
                    "Code/file mutation requires a worker candidate.",
                )
            if not selected.permission_granted:
                return self._blocked(
                    selected,
                    "Worker permission has not been explicitly granted.",
                )
            return self._selected(
                selected,
                execution="worker",
                live=selected.locality is not RouteLocality.LOCAL,
                reason="Explicit governed worker route selected.",
            )

        if selected.kind is not CandidateKind.AI:
            return self._blocked(
                selected,
                "Analysis/private/live tasks require an AI candidate.",
            )

        if request.task_kind is TaskKind.PRIVATE_SIMPLE:
            if request.privacy_required and not selected.privacy_safe:
                return self._blocked(
                    selected,
                    "Selected route does not satisfy privacy requirement.",
                )
            if request.mode is HybridMode.OFFLINE and (
                selected.locality is not RouteLocality.LOCAL
            ):
                return self._blocked(
                    selected,
                    "OFFLINE mode cannot use loopback/cloud AI.",
                )
            return self._selected(
                selected,
                execution="ai",
                live=False,
                reason="Explicit private/simple AI route selected.",
            )

        if request.task_kind is TaskKind.SOURCE_ANALYSIS:
            if selected.locality is RouteLocality.CLOUD:
                if not request.explicit_live or request.mode is not HybridMode.LIVE:
                    return self._blocked(
                        selected,
                        "Cloud AI requires explicit LIVE mode.",
                    )
                if not selected.supports_live:
                    return self._blocked(
                        selected,
                        "Selected AI route does not declare LIVE support.",
                    )
                return self._selected(
                    selected,
                    execution="ai",
                    live=True,
                    reason="Explicit LIVE source-analysis route selected.",
                )

            if request.mode not in {HybridMode.ANALYSIS, HybridMode.OFFLINE}:
                return self._blocked(
                    selected,
                    "Local source analysis requires ANALYSIS or OFFLINE mode.",
                )
            return self._selected(
                selected,
                execution="ai",
                live=False,
                reason="Explicit local source-analysis route selected.",
            )

        if request.task_kind is TaskKind.LIVE_RESEARCH:
            if request.mode is not HybridMode.LIVE or not request.explicit_live:
                return self._blocked(
                    selected,
                    "Live research requires explicit LIVE mode.",
                )
            if not selected.supports_live:
                return self._blocked(
                    selected,
                    "Selected route does not support LIVE execution.",
                )
            return self._selected(
                selected,
                execution="ai",
                live=True,
                reason="Explicit LIVE research route selected.",
            )

        return self._blocked(selected, "Unsupported routing request.")

    def fail_selected_route(
        self,
        decision: HybridRoutingDecision,
        *,
        reason: str,
    ) -> HybridRoutingDecision:
        if decision.candidate_id is None:
            raise ValueError("no selected route exists to fail")
        return HybridRoutingDecision(
            status=RoutingStatus.NEEDS_ATTENTION,
            execution=decision.execution,
            candidate_id=decision.candidate_id,
            provider=decision.provider,
            model=decision.model,
            live=decision.live,
            reason=reason,
            alternatives_considered=(),
        )

    def _common_gate(
        self,
        request: HybridRoutingRequest,
        candidate: HybridCandidate,
    ) -> HybridRoutingDecision | None:
        if candidate.readiness is CapabilityState.UNAVAILABLE:
            return self._blocked(candidate, "Selected capability is unavailable.")

        if candidate.readiness in {
            CapabilityState.NEEDS_ATTENTION,
            CapabilityState.NOT_CHECKED,
        }:
            return HybridRoutingDecision(
                status=RoutingStatus.NEEDS_ATTENTION,
                execution="none",
                candidate_id=candidate.candidate_id,
                provider=candidate.provider,
                model=candidate.model,
                live=False,
                reason=(
                    "Selected capability is not currently confirmed available."
                ),
            )

        if candidate.quota is QuotaState.EXHAUSTED:
            return HybridRoutingDecision(
                status=RoutingStatus.NEEDS_ATTENTION,
                execution="none",
                candidate_id=candidate.candidate_id,
                provider=candidate.provider,
                model=candidate.model,
                live=False,
                reason="Selected route quota is exhausted.",
            )

        if candidate.cost_class == "paid" and not request.allow_paid:
            return self._blocked(
                candidate,
                "Paid route requires explicit allow_paid approval.",
            )

        if candidate.cost_class == "unknown" and not request.allow_paid:
            return self._blocked(
                candidate,
                "Unknown-cost route requires explicit cost approval.",
            )

        return None

    @staticmethod
    def _selected(
        candidate: HybridCandidate,
        *,
        execution: str,
        live: bool,
        reason: str,
    ) -> HybridRoutingDecision:
        return HybridRoutingDecision(
            status=RoutingStatus.SELECTED,
            execution=execution,
            candidate_id=candidate.candidate_id,
            provider=candidate.provider,
            model=candidate.model,
            live=live,
            reason=reason,
        )

    @staticmethod
    def _blocked(
        candidate: HybridCandidate,
        reason: str,
    ) -> HybridRoutingDecision:
        return HybridRoutingDecision(
            status=RoutingStatus.BLOCKED,
            execution="none",
            candidate_id=candidate.candidate_id,
            provider=candidate.provider,
            model=candidate.model,
            live=False,
            reason=reason,
        )


__all__ = [
    "CandidateKind",
    "HybridCandidate",
    "HybridMode",
    "HybridRouter",
    "HybridRoutingDecision",
    "HybridRoutingRequest",
    "LatencyClass",
    "ProviderFailureKind",
    "QuotaState",
    "RouteLocality",
    "RoutingStatus",
    "TaskKind",
    "classify_provider_failure",
]
