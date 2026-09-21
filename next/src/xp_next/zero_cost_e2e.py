from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from .apply_control import (
    ApplyResult,
    ApplyStatus,
    apply_reviewed_sandbox,
    discard_reviewed_sandbox,
)
from .isolated_workspace import prepare_isolated_workspace
from .job_state import JobState
from .planner import BoundedReadOnlyPlanner, PlanStatus, verify_plan
from .project_service import ProjectService
from .reasoning import ReasoningRequest, ReasoningStatus, compact_reasoning_context
from .runtime_paths import RuntimePaths
from .sandbox_review import ReviewBundle, ReviewStatus, VerifierSpec, build_review_bundle
from .state_store import StateStore
from .task_contract import TaskIntent, TaskIntentKind
from .worker_contract import WorkerRequest, WorkerStatus


class ReviewAction(str, Enum):
    APPLY = "APPLY"
    DISCARD = "DISCARD"


@dataclass(frozen=True)
class HumanApproval:
    granted: bool
    reviewer: str = "human"

    def __post_init__(self) -> None:
        if self.reviewer != "human":
            raise ValueError("approval must come from an explicit human reviewer")


@dataclass(frozen=True)
class HumanReviewDecision:
    action: ReviewAction
    approved_change_fingerprint: str
    reviewer: str = "human"

    def __post_init__(self) -> None:
        if self.reviewer != "human":
            raise ValueError("review decision must come from an explicit human reviewer")
        if not self.approved_change_fingerprint.strip():
            raise ValueError("approved change fingerprint must not be empty")


@dataclass(frozen=True)
class ZeroCostE2EResult:
    job_id: str
    job_state: str
    reasoning_status: str
    plan_status: str
    worker_status: str
    review_status: str | None
    apply_status: str | None
    sandbox_root: str | None
    recovery_ref: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "job_state": self.job_state,
            "reasoning_status": self.reasoning_status,
            "plan_status": self.plan_status,
            "worker_status": self.worker_status,
            "review_status": self.review_status,
            "apply_status": self.apply_status,
            "sandbox_root": self.sandbox_root,
            "recovery_ref": self.recovery_ref,
        }


ReviewDecider = Callable[[ReviewBundle], HumanReviewDecision]


class ZeroCostE2EService:
    """Fixture-safe zero-cost orchestration across the existing XP Next controls."""

    def __init__(
        self,
        *,
        store: StateStore,
        projects: ProjectService,
        paths: RuntimePaths,
        reasoner: object,
        planner: BoundedReadOnlyPlanner,
        worker: object,
    ):
        self.store = store
        self.projects = projects
        self.paths = paths
        self.reasoner = reasoner
        self.planner = planner
        self.worker = worker

    @staticmethod
    def _activity_id(job_id: str, ordinal: int) -> str:
        return f"{job_id}:activity:{ordinal:02d}"

    def _activity(
        self,
        job_id: str,
        ordinal: int,
        *,
        category: str,
        action: str,
        status: str,
        summary: str,
        source: str | None = None,
        processor: str | None = None,
    ) -> None:
        self.store.record_activity(
            self._activity_id(job_id, ordinal),
            job_id=job_id,
            category=category,
            action=action,
            status=status,
            summary=summary,
            source=source,
            processor=processor,
            live=False,
        )

    def _result(
        self,
        *,
        job_id: str,
        reasoning_status: str,
        plan_status: str,
        worker_status: str,
        review_status: str | None,
        apply_status: str | None,
        sandbox_root: str | None,
        recovery_ref: str | None,
    ) -> ZeroCostE2EResult:
        job = self.store.get_job(job_id)
        return ZeroCostE2EResult(
            job_id=job_id,
            job_state=str(job["state"]),
            reasoning_status=reasoning_status,
            plan_status=plan_status,
            worker_status=worker_status,
            review_status=review_status,
            apply_status=apply_status,
            sandbox_root=sandbox_root,
            recovery_ref=recovery_ref,
        )

    def run(
        self,
        *,
        job_id: str,
        project_id: str,
        goal: str,
        worker_prompt: str,
        verifier_specs: tuple[VerifierSpec, ...],
        sandbox_write_approval: HumanApproval,
        review_decider: ReviewDecider,
        max_reasoning_tokens: int = 96,
    ) -> ZeroCostE2EResult:
        if not verifier_specs:
            raise ValueError("CP-08A requires at least one explicit verifier")
        if not worker_prompt.strip():
            raise ValueError("worker_prompt must not be empty")

        project = self.store.get_project(project_id)
        source_root = Path(str(project["root_path"])).expanduser().resolve(strict=True)

        self.store.create_job(job_id, project_id, goal, risk="write")
        self.store.transition_job(job_id, JobState.PLANNING)

        task = TaskIntent.read_only(goal=goal, kind=TaskIntentKind.ANALYZE)

        qwen_ready = self.reasoner.readiness()
        worker_ready = self.worker.readiness()
        worker_backend = str(getattr(worker_ready, "backend_id", "worker"))
        capabilities = {
            "local_qwen": {
                "state": "READY" if qwen_ready.ready else "NEEDS_ATTENTION",
                "version": getattr(self.reasoner, "model", None),
                "network_used": bool(getattr(qwen_ready, "external_network_used", False)),
            },
            worker_backend: {
                "state": "READY" if worker_ready.ready else "NEEDS_ATTENTION",
                "version": None,
                "network_used": False,
            },
        }

        self._activity(
            job_id,
            1,
            category="project",
            action="inspect_context",
            status="Selesai",
            summary="Bounded local project context requested without external network.",
            source="local_project",
        )

        if (
            not qwen_ready.ready
            or bool(getattr(qwen_ready, "external_network_used", False))
            or not worker_ready.ready
        ):
            self.store.transition_job(job_id, JobState.NEEDS_ATTENTION)
            self._activity(
                job_id,
                2,
                category="capability",
                action="zero_cost_readiness",
                status="Perlu perhatian",
                summary="Required local Qwen or selected worker capability is not ready.",
                source="local",
            )
            return self._result(
                job_id=job_id,
                reasoning_status="NOT_RUN",
                plan_status="NOT_RUN",
                worker_status="NOT_RUN",
                review_status=None,
                apply_status=None,
                sandbox_root=None,
                recovery_ref=None,
            )

        context = self.projects.context(
            task=task,
            capabilities=capabilities,
            project_id=project_id,
        )
        compact_context = compact_reasoning_context(context)

        reasoning = self.reasoner.reason(
            ReasoningRequest(
                task=task,
                context=compact_context,
                max_tokens=max_reasoning_tokens,
            )
        )
        self._activity(
            job_id,
            2,
            category="ai",
            action="local_reasoning",
            status="Selesai" if reasoning.status is ReasoningStatus.COMPLETED else "Perlu perhatian",
            summary=f"Local reasoning backend status: {reasoning.status.value}.",
            source="local_loopback",
            processor="local_qwen",
        )
        if reasoning.status is not ReasoningStatus.COMPLETED:
            self.store.transition_job(job_id, JobState.NEEDS_ATTENTION)
            return self._result(
                job_id=job_id,
                reasoning_status=reasoning.status.value,
                plan_status="NOT_RUN",
                worker_status="NOT_RUN",
                review_status=None,
                apply_status=None,
                sandbox_root=None,
                recovery_ref=None,
            )

        plan = self.planner.build(
            task=task,
            context=compact_context,
            reasoning=reasoning,
        )
        plan_ok, _ = verify_plan(plan)
        self._activity(
            job_id,
            3,
            category="plan",
            action="build_bounded_plan",
            status="Selesai" if plan_ok else "Perlu perhatian",
            summary="Bounded read-only plan compiled from verified local reasoning.",
            source="local",
            processor="xp_next_planner",
        )
        if not plan_ok or plan.status is not PlanStatus.READY:
            self.store.transition_job(job_id, JobState.NEEDS_ATTENTION)
            return self._result(
                job_id=job_id,
                reasoning_status=reasoning.status.value,
                plan_status=plan.status.value,
                worker_status="NOT_RUN",
                review_status=None,
                apply_status=None,
                sandbox_root=None,
                recovery_ref=None,
            )

        self.store.transition_job(job_id, JobState.READY)
        self.store.transition_job(job_id, JobState.AWAITING_APPROVAL)
        self.store.record_approval(
            f"{job_id}:approval:sandbox",
            job_id=job_id,
            approval_class="sandbox_write",
            granted=sandbox_write_approval.granted,
        )
        self._activity(
            job_id,
            4,
            category="approval",
            action="sandbox_write",
            status="Selesai" if sandbox_write_approval.granted else "Gagal",
            summary="Explicit human decision recorded for isolated sandbox write.",
            source="human",
        )
        if not sandbox_write_approval.granted:
            self.store.transition_job(job_id, JobState.CANCELLED)
            return self._result(
                job_id=job_id,
                reasoning_status=reasoning.status.value,
                plan_status=plan.status.value,
                worker_status="NOT_RUN",
                review_status=None,
                apply_status=None,
                sandbox_root=None,
                recovery_ref=None,
            )

        self.store.transition_job(job_id, JobState.RUNNING)
        isolated = prepare_isolated_workspace(
            source_root,
            self.paths.workspaces,
            job_id=job_id,
        )
        worker_result = self.worker.run(
            WorkerRequest(
                job_id=job_id,
                prompt=worker_prompt,
                workspace_root=isolated.root,
                cwd=isolated.project,
            ),
            home=isolated.home,
            tmp=isolated.tmp,
        )
        self._activity(
            job_id,
            5,
            category="worker",
            action=f"isolated_{worker_backend}",
            status="Selesai" if worker_result.status is WorkerStatus.COMPLETED else "Perlu perhatian",
            summary=worker_result.detail or f"Worker status: {worker_result.status.value}.",
            source="isolated_workspace",
            processor=worker_backend,
        )
        if worker_result.status is not WorkerStatus.COMPLETED:
            self.store.transition_job(job_id, JobState.NEEDS_ATTENTION)
            return self._result(
                job_id=job_id,
                reasoning_status=reasoning.status.value,
                plan_status=plan.status.value,
                worker_status=worker_result.status.value,
                review_status=None,
                apply_status=None,
                sandbox_root=str(isolated.project),
                recovery_ref=None,
            )

        self.store.transition_job(job_id, JobState.VERIFYING)
        review = build_review_bundle(
            isolated.project,
            verifier_specs=verifier_specs,
        )
        self._activity(
            job_id,
            6,
            category="verification",
            action="sandbox_review",
            status="Selesai" if review.status is ReviewStatus.PASS else "Perlu perhatian",
            summary=review.summary,
            source="isolated_workspace",
            processor="xp_next_verifier",
        )
        if review.status is not ReviewStatus.PASS:
            self.store.transition_job(job_id, JobState.NEEDS_ATTENTION)
            return self._result(
                job_id=job_id,
                reasoning_status=reasoning.status.value,
                plan_status=plan.status.value,
                worker_status=worker_result.status.value,
                review_status=review.status.value,
                apply_status=None,
                sandbox_root=str(isolated.project),
                recovery_ref=None,
            )

        self.store.transition_job(job_id, JobState.READY_TO_REVIEW)
        decision = review_decider(review)
        if decision.approved_change_fingerprint != review.change_fingerprint:
            self.store.transition_job(job_id, JobState.NEEDS_ATTENTION)
            self._activity(
                job_id,
                7,
                category="review",
                action="human_review",
                status="Perlu perhatian",
                summary="Human decision fingerprint did not match the reviewed change.",
                source="human",
            )
            return self._result(
                job_id=job_id,
                reasoning_status=reasoning.status.value,
                plan_status=plan.status.value,
                worker_status=worker_result.status.value,
                review_status=review.status.value,
                apply_status=None,
                sandbox_root=str(isolated.project),
                recovery_ref=None,
            )

        is_apply = decision.action is ReviewAction.APPLY
        self.store.record_approval(
            f"{job_id}:approval:apply",
            job_id=job_id,
            approval_class="apply_original",
            granted=is_apply,
        )
        self._activity(
            job_id,
            7,
            category="review",
            action="human_review",
            status="Selesai",
            summary=f"Explicit human review decision recorded: {decision.action.value}.",
            source="human",
        )

        source_identity = dict(context.get("source_identity", {}))
        expected_head = str(source_identity.get("head") or "")
        if not expected_head:
            self.store.transition_job(job_id, JobState.NEEDS_ATTENTION)
            return self._result(
                job_id=job_id,
                reasoning_status=reasoning.status.value,
                plan_status=plan.status.value,
                worker_status=worker_result.status.value,
                review_status=review.status.value,
                apply_status=None,
                sandbox_root=str(isolated.project),
                recovery_ref=None,
            )

        if decision.action is ReviewAction.DISCARD:
            discarded = discard_reviewed_sandbox(
                original_root=source_root,
                sandbox_root=isolated.project,
                approved_review=review,
                verifier_specs=verifier_specs,
                expected_original_head=expected_head,
            )
            self.store.transition_job(job_id, JobState.CANCELLED)
            self._activity(
                job_id,
                8,
                category="apply",
                action="discard",
                status="Selesai",
                summary="Reviewed sandbox discarded; original project remained unchanged.",
                source="local",
                processor="xp_next_apply_control",
            )
            return self._result(
                job_id=job_id,
                reasoning_status=reasoning.status.value,
                plan_status=plan.status.value,
                worker_status=worker_result.status.value,
                review_status=review.status.value,
                apply_status=discarded.status.value,
                sandbox_root=str(isolated.project),
                recovery_ref=None,
            )

        self.store.transition_job(job_id, JobState.APPLYING)
        applied: ApplyResult = apply_reviewed_sandbox(
            original_root=source_root,
            sandbox_root=isolated.project,
            approved_review=review,
            verifier_specs=verifier_specs,
            expected_original_head=expected_head,
            recovery_parent=self.paths.artifacts / "recovery",
            recovery_id=f"{job_id}-apply",
        )
        if applied.recovery_ref:
            self.store.record_recovery_point(
                f"{job_id}:recovery:apply",
                project_id=project_id,
                source_ref=applied.recovery_ref,
                job_id=job_id,
            )

        self._activity(
            job_id,
            8,
            category="apply",
            action="apply_reviewed_change",
            status="Selesai" if applied.status is ApplyStatus.APPLIED else "Perlu perhatian",
            summary=applied.detail,
            source="local_project",
            processor="xp_next_apply_control",
        )

        if applied.status is ApplyStatus.ROLLED_BACK:
            self.store.transition_job(job_id, JobState.ROLLED_BACK)
        elif applied.status is ApplyStatus.NEEDS_ATTENTION:
            self.store.transition_job(job_id, JobState.NEEDS_ATTENTION)
        elif applied.status is ApplyStatus.APPLIED:
            self.store.transition_job(job_id, JobState.VERIFYING_APPLIED)
            if applied.post_verify_status != "PASS":
                self.store.transition_job(job_id, JobState.NEEDS_ATTENTION)
            else:
                self._activity(
                    job_id,
                    9,
                    category="verification",
                    action="post_apply_verify",
                    status="Selesai",
                    summary="Post-Apply verifier passed against the original project.",
                    source="local_project",
                    processor="xp_next_verifier",
                )
                self.store.transition_job(job_id, JobState.COMPLETED)

        return self._result(
            job_id=job_id,
            reasoning_status=reasoning.status.value,
            plan_status=plan.status.value,
            worker_status=worker_result.status.value,
            review_status=review.status.value,
            apply_status=applied.status.value,
            sandbox_root=str(isolated.project),
            recovery_ref=applied.recovery_ref,
        )
