from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum

from .reasoning import ReasoningResult, ReasoningStatus, verify_reasoning_result
from .task_contract import TaskIntent, TaskIntentKind


class PlanStatus(str, Enum):
    READY = "READY"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


class PlanStepKind(str, Enum):
    OBSERVE_PROJECT = "OBSERVE_PROJECT"
    REVIEW_SOURCE_IDENTITY = "REVIEW_SOURCE_IDENTITY"
    ANALYZE_CONTEXT = "ANALYZE_CONTEXT"
    EXPLAIN_FINDINGS = "EXPLAIN_FINDINGS"


@dataclass(frozen=True)
class PlanStep:
    ordinal: int
    kind: PlanStepKind
    title: str
    mutation_allowed: bool = False
    network_allowed: bool = False

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["kind"] = self.kind.value
        return data


@dataclass(frozen=True)
class Plan:
    status: PlanStatus
    goal: str
    intent: str
    risk: str
    mutation_allowed: bool
    network_allowed: bool
    reasoning_summary: str
    steps: tuple[PlanStep, ...]
    detail: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "goal": self.goal,
            "intent": self.intent,
            "risk": self.risk,
            "mutation_allowed": self.mutation_allowed,
            "network_allowed": self.network_allowed,
            "reasoning_summary": self.reasoning_summary,
            "steps": [step.as_dict() for step in self.steps],
            "detail": self.detail,
        }


_STEP_TEMPLATES: dict[TaskIntentKind, tuple[tuple[PlanStepKind, str], ...]] = {
    TaskIntentKind.INSPECT: (
        (PlanStepKind.OBSERVE_PROJECT, "Periksa fakta project yang sudah diobservasi"),
        (PlanStepKind.REVIEW_SOURCE_IDENTITY, "Tinjau identitas source dan status Git"),
        (PlanStepKind.EXPLAIN_FINDINGS, "Sajikan temuan read-only secara ringkas"),
    ),
    TaskIntentKind.ANALYZE: (
        (PlanStepKind.OBSERVE_PROJECT, "Periksa fakta project yang sudah diobservasi"),
        (PlanStepKind.ANALYZE_CONTEXT, "Analisis fakta dan hint dalam context"),
        (PlanStepKind.EXPLAIN_FINDINGS, "Sajikan hasil analisis tanpa mengubah project"),
    ),
    TaskIntentKind.EXPLAIN: (
        (PlanStepKind.REVIEW_SOURCE_IDENTITY, "Tinjau identitas source yang relevan"),
        (PlanStepKind.ANALYZE_CONTEXT, "Hubungkan fakta context dengan tujuan pengguna"),
        (PlanStepKind.EXPLAIN_FINDINGS, "Berikan penjelasan yang didukung context"),
    ),
}


class BoundedReadOnlyPlanner:
    """Compile a static read-only plan from verified reasoning and task intent."""

    def build(
        self,
        *,
        task: TaskIntent,
        context: dict[str, object],
        reasoning: ReasoningResult,
    ) -> Plan:
        if (
            task.risk != "read"
            or task.mutation_allowed
            or task.network_allowed
            or bool(context.get("network_used"))
        ):
            return Plan(
                status=PlanStatus.NEEDS_ATTENTION,
                goal=task.goal,
                intent=task.kind.value,
                risk="read",
                mutation_allowed=False,
                network_allowed=False,
                reasoning_summary="",
                steps=(),
                detail="planner accepts only local read-only context and tasks",
            )

        reasoning_ok, reasoning_detail = verify_reasoning_result(reasoning)
        if not reasoning_ok:
            return Plan(
                status=PlanStatus.NEEDS_ATTENTION,
                goal=task.goal,
                intent=task.kind.value,
                risk="read",
                mutation_allowed=False,
                network_allowed=False,
                reasoning_summary="",
                steps=(),
                detail=reasoning_detail,
            )

        templates = _STEP_TEMPLATES[task.kind]
        steps = tuple(
            PlanStep(
                ordinal=index,
                kind=kind,
                title=title,
                mutation_allowed=False,
                network_allowed=False,
            )
            for index, (kind, title) in enumerate(templates, start=1)
        )
        return Plan(
            status=PlanStatus.READY,
            goal=task.goal,
            intent=task.kind.value,
            risk="read",
            mutation_allowed=False,
            network_allowed=False,
            reasoning_summary=reasoning.output.strip()[:1200],
            steps=steps,
        )


def verify_plan(plan: Plan) -> tuple[bool, str]:
    if plan.status is not PlanStatus.READY:
        return False, plan.detail or "plan is not ready"
    if plan.risk != "read":
        return False, "plan risk must remain read"
    if plan.mutation_allowed:
        return False, "plan mutation must remain disabled"
    if plan.network_allowed:
        return False, "plan network access must remain disabled"
    if not (1 <= len(plan.steps) <= 4):
        return False, "plan must contain between 1 and 4 steps"
    for expected, step in enumerate(plan.steps, start=1):
        if step.ordinal != expected:
            return False, "plan ordinals must be contiguous"
        if not isinstance(step.kind, PlanStepKind):
            return False, "unknown plan step kind"
        if step.mutation_allowed:
            return False, f"step {expected} enables mutation"
        if step.network_allowed:
            return False, f"step {expected} enables network access"
        if not step.title.strip():
            return False, f"step {expected} title is empty"
    if not plan.reasoning_summary.strip():
        return False, "reasoning summary is empty"
    return True, "PASS"
