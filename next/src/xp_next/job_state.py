from __future__ import annotations
from enum import Enum

class JobState(str, Enum):
    DRAFT = "DRAFT"
    PLANNING = "PLANNING"
    READY = "READY"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    READY_TO_REVIEW = "READY_TO_REVIEW"
    APPLYING = "APPLYING"
    VERIFYING_APPLIED = "VERIFYING_APPLIED"
    COMPLETED = "COMPLETED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    ROLLED_BACK = "ROLLED_BACK"
    CANCELLED = "CANCELLED"

_ALLOWED = {
    JobState.DRAFT: frozenset({JobState.PLANNING, JobState.CANCELLED}),
    JobState.PLANNING: frozenset({JobState.READY, JobState.NEEDS_ATTENTION, JobState.CANCELLED}),
    JobState.READY: frozenset({JobState.AWAITING_APPROVAL, JobState.RUNNING, JobState.CANCELLED}),
    JobState.AWAITING_APPROVAL: frozenset({JobState.RUNNING, JobState.CANCELLED}),
    JobState.RUNNING: frozenset({JobState.VERIFYING, JobState.NEEDS_ATTENTION, JobState.ROLLED_BACK, JobState.CANCELLED}),
    JobState.VERIFYING: frozenset({JobState.READY_TO_REVIEW, JobState.NEEDS_ATTENTION, JobState.ROLLED_BACK}),
    JobState.READY_TO_REVIEW: frozenset({JobState.APPLYING, JobState.CANCELLED}),
    JobState.APPLYING: frozenset({JobState.VERIFYING_APPLIED, JobState.ROLLED_BACK, JobState.NEEDS_ATTENTION}),
    JobState.VERIFYING_APPLIED: frozenset({JobState.COMPLETED, JobState.ROLLED_BACK, JobState.NEEDS_ATTENTION}),
    JobState.NEEDS_ATTENTION: frozenset({JobState.PLANNING, JobState.ROLLED_BACK, JobState.CANCELLED}),
    JobState.COMPLETED: frozenset(),
    JobState.ROLLED_BACK: frozenset(),
    JobState.CANCELLED: frozenset(),
}

def can_transition(current: JobState, target: JobState) -> bool:
    return target in _ALLOWED[current]
