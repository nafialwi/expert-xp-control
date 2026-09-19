from __future__ import annotations

import unittest

from xp.capabilities import CapabilityState
from xp.ai.hybrid_routing import (
    CandidateKind,
    HybridCandidate,
    HybridMode,
    HybridRouter,
    HybridRoutingRequest,
    LatencyClass,
    ProviderFailureKind,
    QuotaState,
    RouteLocality,
    RoutingStatus,
    TaskKind,
    classify_provider_failure,
)


def ai(
    candidate_id,
    *,
    locality=RouteLocality.LOCAL,
    readiness=CapabilityState.AVAILABLE,
    quota=QuotaState.OK,
    cost="free",
    supports_live=False,
    privacy_safe=True,
):
    return HybridCandidate(
        candidate_id=candidate_id,
        kind=CandidateKind.AI,
        provider="provider-" + candidate_id,
        model="model-" + candidate_id,
        locality=locality,
        cost_class=cost,
        readiness=readiness,
        quota=quota,
        latency=LatencyClass.LOW,
        supports_live=supports_live,
        privacy_safe=privacy_safe,
    )


def worker(candidate_id, *, permission=True):
    return HybridCandidate(
        candidate_id=candidate_id,
        kind=CandidateKind.WORKER,
        provider="worker-" + candidate_id,
        model="runtime-" + candidate_id,
        locality=RouteLocality.LOCAL,
        cost_class="free",
        readiness=CapabilityState.AVAILABLE,
        quota=QuotaState.OK,
        permission_granted=permission,
    )


class AF08HybridRoutingTests(unittest.TestCase):
    def setUp(self):
        self.router = HybridRouter()

    def test_deterministic_task_never_requires_ai(self):
        decision = self.router.route(
            HybridRoutingRequest(
                task_kind=TaskKind.DETERMINISTIC,
                mode=HybridMode.OFFLINE,
            ),
            (ai("qwen"), ai("router")),
        )
        self.assertIs(decision.status, RoutingStatus.DETERMINISTIC)
        self.assertEqual(decision.execution, "deterministic_tool")
        self.assertIsNone(decision.candidate_id)

    def test_ai_route_requires_explicit_user_selection(self):
        decision = self.router.route(
            HybridRoutingRequest(
                task_kind=TaskKind.SOURCE_ANALYSIS,
                mode=HybridMode.ANALYSIS,
            ),
            (ai("qwen"), ai("router")),
        )
        self.assertIs(
            decision.status,
            RoutingStatus.USER_CHOICE_REQUIRED,
        )
        self.assertEqual(
            decision.alternatives_considered,
            ("qwen", "router"),
        )

    def test_no_silent_fallback_after_selected_route_failure(self):
        selected = self.router.route(
            HybridRoutingRequest(
                task_kind=TaskKind.SOURCE_ANALYSIS,
                mode=HybridMode.ANALYSIS,
                selected_candidate_id="qwen",
            ),
            (ai("qwen"), ai("router")),
        )
        failed = self.router.fail_selected_route(
            selected,
            reason="selected route failed",
        )
        self.assertIs(failed.status, RoutingStatus.NEEDS_ATTENTION)
        self.assertEqual(failed.candidate_id, "qwen")
        self.assertEqual(failed.alternatives_considered, ())

    def test_quota_exhaustion_never_switches_candidate(self):
        decision = self.router.route(
            HybridRoutingRequest(
                task_kind=TaskKind.SOURCE_ANALYSIS,
                mode=HybridMode.ANALYSIS,
                selected_candidate_id="qwen",
            ),
            (
                ai("qwen", quota=QuotaState.EXHAUSTED),
                ai("router"),
            ),
        )
        self.assertIs(decision.status, RoutingStatus.NEEDS_ATTENTION)
        self.assertEqual(decision.candidate_id, "qwen")

    def test_not_checked_is_not_available(self):
        decision = self.router.route(
            HybridRoutingRequest(
                task_kind=TaskKind.SOURCE_ANALYSIS,
                mode=HybridMode.ANALYSIS,
                selected_candidate_id="qwen",
            ),
            (ai("qwen", readiness=CapabilityState.NOT_CHECKED),),
        )
        self.assertIs(decision.status, RoutingStatus.NEEDS_ATTENTION)

    def test_paid_route_requires_explicit_approval(self):
        decision = self.router.route(
            HybridRoutingRequest(
                task_kind=TaskKind.SOURCE_ANALYSIS,
                mode=HybridMode.ANALYSIS,
                selected_candidate_id="paid",
            ),
            (ai("paid", cost="paid"),),
        )
        self.assertIs(decision.status, RoutingStatus.BLOCKED)

        allowed = self.router.route(
            HybridRoutingRequest(
                task_kind=TaskKind.SOURCE_ANALYSIS,
                mode=HybridMode.ANALYSIS,
                selected_candidate_id="paid",
                allow_paid=True,
            ),
            (ai("paid", cost="paid"),),
        )
        self.assertIs(allowed.status, RoutingStatus.SELECTED)

    def test_private_offline_task_blocks_cloud_route(self):
        decision = self.router.route(
            HybridRoutingRequest(
                task_kind=TaskKind.PRIVATE_SIMPLE,
                mode=HybridMode.OFFLINE,
                selected_candidate_id="cloud",
                privacy_required=True,
            ),
            (
                ai(
                    "cloud",
                    locality=RouteLocality.CLOUD,
                    privacy_safe=False,
                    supports_live=True,
                ),
            ),
        )
        self.assertIs(decision.status, RoutingStatus.BLOCKED)

    def test_cloud_source_analysis_requires_explicit_live(self):
        cloud = ai(
            "cloud",
            locality=RouteLocality.CLOUD,
            supports_live=True,
        )
        blocked = self.router.route(
            HybridRoutingRequest(
                task_kind=TaskKind.SOURCE_ANALYSIS,
                mode=HybridMode.ANALYSIS,
                selected_candidate_id="cloud",
            ),
            (cloud,),
        )
        self.assertIs(blocked.status, RoutingStatus.BLOCKED)

        allowed = self.router.route(
            HybridRoutingRequest(
                task_kind=TaskKind.SOURCE_ANALYSIS,
                mode=HybridMode.LIVE,
                selected_candidate_id="cloud",
                explicit_live=True,
            ),
            (cloud,),
        )
        self.assertIs(allowed.status, RoutingStatus.SELECTED)
        self.assertTrue(allowed.live)

    def test_worker_route_requires_worker_mode_and_permission(self):
        candidate = worker("hermes", permission=False)
        blocked = self.router.route(
            HybridRoutingRequest(
                task_kind=TaskKind.CODE_MUTATION,
                mode=HybridMode.WORKER,
                selected_candidate_id="hermes",
            ),
            (candidate,),
        )
        self.assertIs(blocked.status, RoutingStatus.BLOCKED)

        candidate = worker("hermes", permission=True)
        allowed = self.router.route(
            HybridRoutingRequest(
                task_kind=TaskKind.CODE_MUTATION,
                mode=HybridMode.WORKER,
                selected_candidate_id="hermes",
            ),
            (candidate,),
        )
        self.assertIs(allowed.status, RoutingStatus.SELECTED)
        self.assertEqual(allowed.execution, "worker")

    def test_source_provenance_is_separate_from_processor_identity(self):
        decision = self.router.route(
            HybridRoutingRequest(
                task_kind=TaskKind.SOURCE_ANALYSIS,
                mode=HybridMode.ANALYSIS,
                selected_candidate_id="qwen",
            ),
            (ai("qwen"),),
        )
        provenance = decision.provenance_for(
            "src/xp/ai/hybrid_routing.py"
        )
        self.assertEqual(
            provenance.source,
            "src/xp/ai/hybrid_routing.py",
        )
        self.assertEqual(
            provenance.processor,
            "provider-qwen:model-qwen",
        )
        self.assertEqual(provenance.via, "hybrid_router")
        self.assertFalse(provenance.live)

    def test_provider_failure_classification_nested_quota_under_503(self):
        detail = (
            'outer HTTP 503: {"error":{"message":'
            '"[gemini] [429] RESOURCE_EXHAUSTED quota exceeded"}}'
        )
        self.assertIs(
            classify_provider_failure(
                http_status=503,
                detail=detail,
            ),
            ProviderFailureKind.QUOTA_OR_RATE_LIMIT,
        )

    def test_provider_failure_classification_auth(self):
        self.assertIs(
            classify_provider_failure(
                http_status=401,
                detail="Unauthorized",
            ),
            ProviderFailureKind.AUTHENTICATION,
        )

    def test_provider_failure_classification_temporary(self):
        self.assertIs(
            classify_provider_failure(
                http_status=503,
                detail="service unavailable",
            ),
            ProviderFailureKind.TEMPORARILY_UNAVAILABLE,
        )

    def test_provider_failure_classification_timeout(self):
        self.assertIs(
            classify_provider_failure(
                http_status=None,
                detail="operation timed out",
                timed_out=True,
            ),
            ProviderFailureKind.TIMEOUT,
        )

    def test_router_is_pure_offline_no_probe_callable_exists(self):
        candidate = ai("qwen")
        decision = self.router.route(
            HybridRoutingRequest(
                task_kind=TaskKind.PRIVATE_SIMPLE,
                mode=HybridMode.OFFLINE,
                selected_candidate_id="qwen",
                privacy_required=True,
            ),
            (candidate,),
        )
        self.assertIs(decision.status, RoutingStatus.SELECTED)


if __name__ == "__main__":
    unittest.main()
