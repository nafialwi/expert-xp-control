from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xp.capabilities import CapabilityState
from xp.ai.hybrid_routing import (
    CandidateKind,
    HybridCandidate,
    HybridMode,
    HybridRouter,
    HybridRoutingRequest,
    QuotaState,
    RouteLocality,
    RoutingStatus,
    TaskKind,
)
from xp.orchestration import (
    BoundedPlan,
    ContextItem,
    ExecutionReport,
    OrchestrationRequest,
    OrchestrationStatus,
    PlanStep,
    ProjectOrchestrator,
    ProjectRef,
    VerificationReport,
)


def local_ai():
    return HybridCandidate(
        candidate_id="qwen",
        kind=CandidateKind.AI,
        provider="local",
        model="qwen",
        locality=RouteLocality.LOCAL,
        cost_class="free",
        readiness=CapabilityState.AVAILABLE,
        quota=QuotaState.OK,
        privacy_safe=True,
    )


def cloud_ai():
    return HybridCandidate(
        candidate_id="cloud",
        kind=CandidateKind.AI,
        provider="9router",
        model="cloud-model",
        locality=RouteLocality.CLOUD,
        cost_class="free",
        readiness=CapabilityState.AVAILABLE,
        quota=QuotaState.OK,
        supports_live=True,
    )


def worker(permission=True):
    return HybridCandidate(
        candidate_id="worker",
        kind=CandidateKind.WORKER,
        provider="hermes",
        model="runtime",
        locality=RouteLocality.LOCAL,
        cost_class="free",
        readiness=CapabilityState.AVAILABLE,
        quota=QuotaState.OK,
        permission_granted=permission,
    )


class AF10FinalAcceptanceTests(unittest.TestCase):
    def test_offline_local_ai_route(self):
        decision = HybridRouter().route(
            HybridRoutingRequest(
                task_kind=TaskKind.PRIVATE_SIMPLE,
                mode=HybridMode.OFFLINE,
                selected_candidate_id="qwen",
                privacy_required=True,
            ),
            (local_ai(),),
        )
        self.assertIs(decision.status, RoutingStatus.SELECTED)
        self.assertFalse(decision.live)

    def test_analysis_explicit_local_route(self):
        decision = HybridRouter().route(
            HybridRoutingRequest(
                task_kind=TaskKind.SOURCE_ANALYSIS,
                mode=HybridMode.ANALYSIS,
                selected_candidate_id="qwen",
            ),
            (local_ai(),),
        )
        self.assertIs(decision.status, RoutingStatus.SELECTED)
        self.assertEqual(decision.provider, "local")
        self.assertEqual(decision.model, "qwen")

    def test_live_remains_explicit(self):
        blocked = HybridRouter().route(
            HybridRoutingRequest(
                task_kind=TaskKind.LIVE_RESEARCH,
                mode=HybridMode.ANALYSIS,
                selected_candidate_id="cloud",
            ),
            (cloud_ai(),),
        )
        self.assertIs(blocked.status, RoutingStatus.BLOCKED)

        allowed = HybridRouter().route(
            HybridRoutingRequest(
                task_kind=TaskKind.LIVE_RESEARCH,
                mode=HybridMode.LIVE,
                selected_candidate_id="cloud",
                explicit_live=True,
            ),
            (cloud_ai(),),
        )
        self.assertIs(allowed.status, RoutingStatus.SELECTED)
        self.assertTrue(allowed.live)

    def test_no_silent_fallback_after_selected_failure(self):
        router = HybridRouter()
        selected = router.route(
            HybridRoutingRequest(
                task_kind=TaskKind.SOURCE_ANALYSIS,
                mode=HybridMode.ANALYSIS,
                selected_candidate_id="qwen",
            ),
            (local_ai(), cloud_ai()),
        )
        failed = router.fail_selected_route(
            selected,
            reason="quota",
        )
        self.assertIs(
            failed.status,
            RoutingStatus.NEEDS_ATTENTION,
        )
        self.assertEqual(failed.candidate_id, "qwen")
        self.assertEqual(failed.alternatives_considered, ())

    def test_worker_requires_permission_and_human_approval(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            readme = root / "README.md"
            readme.write_text("x", encoding="utf-8")
            project = ProjectRef(
                project_id="af10",
                name="AF10",
                root=root,
                checkpoint="BASE",
            )
            calls = []
            result = ProjectOrchestrator().run(
                OrchestrationRequest(
                    job_id="af10-worker",
                    message="write",
                    project=project,
                    task_kind=TaskKind.CODE_MUTATION,
                    mode=HybridMode.WORKER,
                    candidates=(worker(permission=True),),
                    selected_candidate_id="worker",
                    approval_granted=False,
                ),
                retriever=lambda _req: (
                    ContextItem(
                        path=readme,
                        kind="doc",
                        summary="readme",
                    ),
                ),
                planner=lambda *_: BoundedPlan(
                    steps=(
                        PlanStep(
                            step_id="write",
                            action="write",
                            requires_write=True,
                        ),
                    )
                ),
                executor=lambda *_: (
                    calls.append("executed")
                    or ExecutionReport(True, "done")
                ),
                verifier=lambda *_: VerificationReport(
                    True, "verified"
                ),
                recovery_factory=lambda _root: "R",
                rollback=lambda _rid: None,
            )
            self.assertIs(
                result.status,
                OrchestrationStatus.BLOCKED,
            )
            self.assertEqual(calls, [])

    def test_recovery_rollback_final_acceptance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            readme = root / "README.md"
            readme.write_text("SAFE", encoding="utf-8")
            project = ProjectRef(
                project_id="af10-rollback",
                name="AF10 Rollback",
                root=root,
                checkpoint="BASE",
            )

            def mutate(*_):
                readme.write_text("BROKEN", encoding="utf-8")
                return ExecutionReport(
                    True, "mutated", ("README.md",)
                )

            def rollback(_rid):
                readme.write_text("SAFE", encoding="utf-8")

            result = ProjectOrchestrator(
                max_remediation=0
            ).run(
                OrchestrationRequest(
                    job_id="af10-rollback",
                    message="mutate",
                    project=project,
                    task_kind=TaskKind.CODE_MUTATION,
                    mode=HybridMode.WORKER,
                    candidates=(worker(permission=True),),
                    selected_candidate_id="worker",
                    approval_granted=True,
                ),
                retriever=lambda _req: (
                    ContextItem(
                        path=readme,
                        kind="doc",
                        summary="readme",
                    ),
                ),
                planner=lambda *_: BoundedPlan(
                    steps=(
                        PlanStep(
                            step_id="write",
                            action="write",
                            requires_write=True,
                        ),
                    )
                ),
                executor=mutate,
                verifier=lambda *_: VerificationReport(
                    False, "fail"
                ),
                recovery_factory=lambda _root: "R1",
                rollback=rollback,
            )
            self.assertIs(
                result.status,
                OrchestrationStatus.ROLLED_BACK,
            )
            self.assertEqual(
                readme.read_text(encoding="utf-8"),
                "SAFE",
            )


if __name__ == "__main__":
    unittest.main()
