from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Sequence
from uuid import uuid4

from xp.activity import (
    ActivityCategory,
    ActivityEvent,
    ActivityStatus,
    ActivityStore,
    Provenance,
)
from xp.ai.hybrid_routing import (
    HybridCandidate,
    HybridMode,
    HybridRouter,
    HybridRoutingDecision,
    HybridRoutingRequest,
    RoutingStatus,
    TaskKind,
)

MAX_CONTEXT_ITEMS = 12
MAX_PLAN_STEPS = 8


class OrchestrationStatus(str, Enum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    NEEDS_ATTENTION = "needs_attention"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class ProjectRef:
    project_id: str
    name: str
    root: Path
    checkpoint: str

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise ValueError("project_id must not be empty")
        if not self.name.strip():
            raise ValueError("name must not be empty")
        if not self.checkpoint.strip():
            raise ValueError("checkpoint must not be empty")
        root = self.root.expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError("project root must exist")
        object.__setattr__(self, "root", root)


@dataclass(frozen=True)
class ContextItem:
    path: Path
    kind: str
    summary: str

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError("context kind must not be empty")
        if not self.summary.strip():
            raise ValueError("context summary must not be empty")


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    action: str
    requires_write: bool = False

    def __post_init__(self) -> None:
        if not self.step_id.strip():
            raise ValueError("step_id must not be empty")
        if not self.action.strip():
            raise ValueError("action must not be empty")


@dataclass(frozen=True)
class BoundedPlan:
    steps: tuple[PlanStep, ...]

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("plan must contain at least one step")
        if len(self.steps) > MAX_PLAN_STEPS:
            raise ValueError("plan exceeds bounded step limit")


@dataclass(frozen=True)
class ExecutionReport:
    ok: bool
    summary: str
    changed_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("execution summary must not be empty")


@dataclass(frozen=True)
class VerificationReport:
    passed: bool
    summary: str

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("verification summary must not be empty")


@dataclass(frozen=True)
class OrchestrationRequest:
    job_id: str
    message: str
    project: ProjectRef
    task_kind: TaskKind
    mode: HybridMode
    candidates: tuple[HybridCandidate, ...] = ()
    selected_candidate_id: str | None = None
    approval_granted: bool = False
    allow_paid: bool = False
    privacy_required: bool = False
    explicit_live: bool = False

    def __post_init__(self) -> None:
        if not self.job_id.strip():
            raise ValueError("job_id must not be empty")
        if not self.message.strip():
            raise ValueError("message must not be empty")


@dataclass(frozen=True)
class OrchestrationResult:
    status: OrchestrationStatus
    project_id: str
    entry_checkpoint: str
    final_checkpoint: str
    context_paths: tuple[str, ...]
    plan_steps: tuple[str, ...]
    route: HybridRoutingDecision
    attempts: int
    verification: VerificationReport
    recovery_id: str | None = None
    rollback_performed: bool = False


Retriever = Callable[[OrchestrationRequest], Sequence[ContextItem]]
Planner = Callable[[OrchestrationRequest, tuple[ContextItem, ...]], BoundedPlan]
RecoveryFactory = Callable[[Path], str]
Executor = Callable[
    [OrchestrationRequest, BoundedPlan, HybridRoutingDecision],
    ExecutionReport,
]
Verifier = Callable[[Path, ExecutionReport], VerificationReport]
Remediator = Callable[
    [OrchestrationRequest, BoundedPlan, HybridRoutingDecision, VerificationReport],
    ExecutionReport,
]
Rollback = Callable[[str], None]
CheckpointWriter = Callable[[OrchestrationRequest, VerificationReport], str]


class ProjectOrchestrator:
    def __init__(
        self,
        *,
        router: HybridRouter | None = None,
        activity_store: ActivityStore | None = None,
        max_remediation: int = 1,
    ) -> None:
        if max_remediation < 0 or max_remediation > 3:
            raise ValueError("max_remediation must be between 0 and 3")
        self.router = router or HybridRouter()
        self.activity_store = activity_store
        self.max_remediation = max_remediation

    def _record(
        self,
        *,
        request: OrchestrationRequest,
        action: str,
        status: ActivityStatus,
        summary: str,
        metadata: dict | None = None,
    ) -> None:
        if self.activity_store is None:
            return
        self.activity_store.append(
            ActivityEvent(
                event_id=str(uuid4()),
                job_id=request.job_id,
                timestamp=datetime.now(timezone.utc),
                category=ActivityCategory.PROJECT,
                action=action,
                provenance=Provenance(
                    source=request.project.project_id,
                    processor="xp-orchestrator",
                    via="af09",
                    live=False,
                ),
                status=status,
                result_summary=summary,
                metadata=dict(metadata or {}),
            )
        )

    @staticmethod
    def _validate_context(
        project: ProjectRef,
        items: Sequence[ContextItem],
    ) -> tuple[ContextItem, ...]:
        if len(items) > MAX_CONTEXT_ITEMS:
            raise ValueError("context exceeds selective retrieval limit")

        normalized = []
        seen = set()
        for item in items:
            path = item.path.expanduser().resolve()
            try:
                path.relative_to(project.root)
            except ValueError as exc:
                raise ValueError(
                    "retrieved context must stay inside project root"
                ) from exc
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            normalized.append(
                ContextItem(path=path, kind=item.kind, summary=item.summary)
            )
        return tuple(normalized)

    def _early_result(
        self,
        request: OrchestrationRequest,
        context: tuple[ContextItem, ...],
        plan: BoundedPlan,
        route: HybridRoutingDecision,
        status: OrchestrationStatus,
        summary: str,
    ) -> OrchestrationResult:
        return OrchestrationResult(
            status=status,
            project_id=request.project.project_id,
            entry_checkpoint=request.project.checkpoint,
            final_checkpoint=request.project.checkpoint,
            context_paths=tuple(
                str(item.path.relative_to(request.project.root))
                for item in context
            ),
            plan_steps=tuple(step.step_id for step in plan.steps),
            route=route,
            attempts=0,
            verification=VerificationReport(False, summary),
        )

    def run(
        self,
        request: OrchestrationRequest,
        *,
        retriever: Retriever,
        planner: Planner,
        executor: Executor,
        verifier: Verifier,
        recovery_factory: RecoveryFactory | None = None,
        remediator: Remediator | None = None,
        rollback: Rollback | None = None,
        checkpoint_writer: CheckpointWriter | None = None,
    ) -> OrchestrationResult:
        self._record(
            request=request,
            action="Project identified",
            status=ActivityStatus.COMPLETED,
            summary="Project identity and entry checkpoint accepted",
            metadata={
                "project_id": request.project.project_id,
                "entry_checkpoint": request.project.checkpoint,
            },
        )

        context = self._validate_context(request.project, retriever(request))
        self._record(
            request=request,
            action="Context retrieval",
            status=ActivityStatus.COMPLETED,
            summary=f"Selected {len(context)} relevant context item(s)",
            metadata={
                "context_count": len(context),
                "paths": [
                    str(item.path.relative_to(request.project.root))
                    for item in context
                ],
            },
        )

        plan = planner(request, context)
        if not isinstance(plan, BoundedPlan):
            raise TypeError("planner must return BoundedPlan")
        self._record(
            request=request,
            action="Bounded plan",
            status=ActivityStatus.COMPLETED,
            summary=f"Prepared {len(plan.steps)} bounded plan step(s)",
            metadata={
                "step_count": len(plan.steps),
                "write_steps": sum(
                    1 for step in plan.steps if step.requires_write
                ),
            },
        )

        route = self.router.route(
            HybridRoutingRequest(
                task_kind=request.task_kind,
                mode=request.mode,
                selected_candidate_id=request.selected_candidate_id,
                allow_paid=request.allow_paid,
                privacy_required=request.privacy_required,
                explicit_live=request.explicit_live,
            ),
            request.candidates,
        )
        self._record(
            request=request,
            action="Route decision",
            status=(
                ActivityStatus.COMPLETED
                if route.status in {
                    RoutingStatus.SELECTED,
                    RoutingStatus.DETERMINISTIC,
                }
                else ActivityStatus.NEEDS_ATTENTION
            ),
            summary=route.reason,
            metadata={
                "routing_status": route.status.value,
                "candidate_id": route.candidate_id,
                "provider": route.provider,
                "model": route.model,
                "execution": route.execution,
            },
        )

        if route.status is RoutingStatus.USER_CHOICE_REQUIRED:
            return self._early_result(
                request, context, plan, route,
                OrchestrationStatus.BLOCKED,
                "Explicit route selection is required",
            )
        if route.status is RoutingStatus.BLOCKED:
            return self._early_result(
                request, context, plan, route,
                OrchestrationStatus.BLOCKED,
                route.reason,
            )
        if route.status is RoutingStatus.NEEDS_ATTENTION:
            return self._early_result(
                request, context, plan, route,
                OrchestrationStatus.NEEDS_ATTENTION,
                route.reason,
            )

        is_mutation = (
            request.task_kind is TaskKind.CODE_MUTATION
            or any(step.requires_write for step in plan.steps)
        )

        if is_mutation and not request.approval_granted:
            self._record(
                request=request,
                action="Approval gate",
                status=ActivityStatus.NEEDS_ATTENTION,
                summary="Mutation blocked because approval was not granted",
            )
            return self._early_result(
                request, context, plan, route,
                OrchestrationStatus.BLOCKED,
                "Explicit mutation approval is required",
            )

        recovery_id = None
        if is_mutation:
            if recovery_factory is None or rollback is None:
                raise ValueError(
                    "mutation requires recovery_factory and rollback"
                )
            recovery_id = recovery_factory(request.project.root)
            if not recovery_id or not recovery_id.strip():
                raise ValueError("recovery_factory must return recovery id")
            self._record(
                request=request,
                action="Recovery point",
                status=ActivityStatus.COMPLETED,
                summary="Recovery point created before mutation",
                metadata={"recovery_id": recovery_id},
            )

        report = executor(request, plan, route)
        if not isinstance(report, ExecutionReport):
            raise TypeError("executor must return ExecutionReport")

        attempts = 1
        self._record(
            request=request,
            action="Execution",
            status=(
                ActivityStatus.COMPLETED
                if report.ok else ActivityStatus.FAILED
            ),
            summary=report.summary,
            metadata={
                "attempt": attempts,
                "changed_paths": list(report.changed_paths),
            },
        )

        verification = verifier(request.project.root, report)
        if not isinstance(verification, VerificationReport):
            raise TypeError("verifier must return VerificationReport")
        self._record(
            request=request,
            action="Verifier",
            status=(
                ActivityStatus.COMPLETED
                if verification.passed else ActivityStatus.FAILED
            ),
            summary=verification.summary,
            metadata={"attempt": attempts},
        )

        while (
            not verification.passed
            and remediator is not None
            and attempts <= self.max_remediation
        ):
            attempts += 1
            self._record(
                request=request,
                action="Bounded remediation",
                status=ActivityStatus.STARTED,
                summary=f"Starting remediation attempt {attempts}",
                metadata={"attempt": attempts},
            )
            report = remediator(request, plan, route, verification)
            if not isinstance(report, ExecutionReport):
                raise TypeError("remediator must return ExecutionReport")
            self._record(
                request=request,
                action="Execution",
                status=(
                    ActivityStatus.COMPLETED
                    if report.ok else ActivityStatus.FAILED
                ),
                summary=report.summary,
                metadata={
                    "attempt": attempts,
                    "changed_paths": list(report.changed_paths),
                },
            )
            verification = verifier(request.project.root, report)
            self._record(
                request=request,
                action="Verifier",
                status=(
                    ActivityStatus.COMPLETED
                    if verification.passed else ActivityStatus.FAILED
                ),
                summary=verification.summary,
                metadata={"attempt": attempts},
            )

        if not verification.passed:
            rolled_back = False
            status = OrchestrationStatus.NEEDS_ATTENTION
            if recovery_id is not None and rollback is not None:
                rollback(recovery_id)
                rolled_back = True
                status = OrchestrationStatus.ROLLED_BACK
                self._record(
                    request=request,
                    action="Recovery rollback",
                    status=ActivityStatus.COMPLETED,
                    summary="Verification remained failed; recovery restored",
                    metadata={"attempts": attempts},
                )
            else:
                self._record(
                    request=request,
                    action="Stop / escalation",
                    status=ActivityStatus.NEEDS_ATTENTION,
                    summary="Verification remained failed; human attention required",
                    metadata={"attempts": attempts},
                )
            return OrchestrationResult(
                status=status,
                project_id=request.project.project_id,
                entry_checkpoint=request.project.checkpoint,
                final_checkpoint=request.project.checkpoint,
                context_paths=tuple(
                    str(item.path.relative_to(request.project.root))
                    for item in context
                ),
                plan_steps=tuple(step.step_id for step in plan.steps),
                route=route,
                attempts=attempts,
                verification=verification,
                recovery_id=recovery_id,
                rollback_performed=rolled_back,
            )

        final_checkpoint = request.project.checkpoint
        if checkpoint_writer is not None:
            final_checkpoint = checkpoint_writer(request, verification)
            if not final_checkpoint or not final_checkpoint.strip():
                raise ValueError(
                    "checkpoint_writer must return checkpoint id"
                )

        self._record(
            request=request,
            action="Checkpoint",
            status=ActivityStatus.COMPLETED,
            summary="Orchestration stopped at verified checkpoint",
            metadata={
                "final_checkpoint": final_checkpoint,
                "attempts": attempts,
            },
        )

        return OrchestrationResult(
            status=OrchestrationStatus.COMPLETED,
            project_id=request.project.project_id,
            entry_checkpoint=request.project.checkpoint,
            final_checkpoint=final_checkpoint,
            context_paths=tuple(
                str(item.path.relative_to(request.project.root))
                for item in context
            ),
            plan_steps=tuple(step.step_id for step in plan.steps),
            route=route,
            attempts=attempts,
            verification=verification,
            recovery_id=recovery_id,
            rollback_performed=False,
        )


__all__ = [
    "BoundedPlan",
    "ContextItem",
    "ExecutionReport",
    "MAX_CONTEXT_ITEMS",
    "MAX_PLAN_STEPS",
    "OrchestrationRequest",
    "OrchestrationResult",
    "OrchestrationStatus",
    "PlanStep",
    "ProjectOrchestrator",
    "ProjectRef",
    "VerificationReport",
]
