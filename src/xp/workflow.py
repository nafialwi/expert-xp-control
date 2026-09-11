from __future__ import annotations

from dataclasses import dataclass

from .models import RunState


class InvalidTransition(ValueError):
    pass


class NetworkUnavailable(RuntimeError):
    pass


PRIMARY_SEQUENCE = [
    "IDLE",
    "PREPARING",
    "PACKAGE_VALIDATED",
    "SOURCE_APPLYING",
    "SOURCE_APPLIED",
    "SOURCE_VERIFIED",
    "REMOTE_SAFEPOINT_PENDING",
    "REMOTE_SAFEPOINT",
    "DB_APPROVAL_REQUIRED",
    "DB_APPLYING",
    "DB_APPLIED",
    "DB_VERIFIED",
    "HUMAN_QA",
    "READY_TO_LOCK",
    "LOCKING",
    "LOCKED_LOCAL",
    "LOCKED_REMOTE",
]
SIDE_STATES = {
    "WAITING_GPT",
    "PAUSED_BY_USER",
    "FAILED_SAFE",
    "RECOVERY_REQUIRED",
    "REMOTE_UNAVAILABLE",
}

_ALLOWED: dict[str, set[str]] = {
    a: {b} for a, b in zip(PRIMARY_SEQUENCE, PRIMARY_SEQUENCE[1:])
}
_ALLOWED.update(
    {
        "IDLE": {"PREPARING"},
        "REMOTE_SAFEPOINT_PENDING": {"REMOTE_SAFEPOINT", "REMOTE_UNAVAILABLE"},
        "REMOTE_UNAVAILABLE": {"REMOTE_SAFEPOINT_PENDING", "PAUSED_BY_USER"},
        "WAITING_GPT": {"PACKAGE_VALIDATED", "PAUSED_BY_USER"},
        "PAUSED_BY_USER": {"PREPARING", "PACKAGE_VALIDATED", "SOURCE_APPLYING", "SOURCE_VERIFIED", "DB_APPLYING", "DB_VERIFIED", "HUMAN_QA"},
        "RECOVERY_REQUIRED": {"PREPARING", "SOURCE_APPLYING", "DB_APPLYING", "WAITING_GPT"},
        "FAILED_SAFE": {"WAITING_GPT", "PAUSED_BY_USER"},
    }
)
_ALLOWED.update(
    {
        "REMOTE_SAFEPOINT": {"DB_APPROVAL_REQUIRED", "HUMAN_QA", "REMOTE_UNAVAILABLE"},
        "LOCKING": {"LOCKED_LOCAL", "LOCKED_REMOTE"},
        "LOCKED_REMOTE": {"LOCKED_LOCAL"},
        "WAITING_GPT": {"SOURCE_APPLYING", "SOURCE_VERIFIED", "PACKAGE_VALIDATED", "PAUSED_BY_USER"},
        "REMOTE_UNAVAILABLE": {"REMOTE_SAFEPOINT_PENDING", "REMOTE_SAFEPOINT", "DB_APPROVAL_REQUIRED", "HUMAN_QA", "PAUSED_BY_USER"},
    }
)


def transition_allowed(current: str, target: str) -> bool:
    return target in _ALLOWED.get(current, set())


for stage in list(PRIMARY_SEQUENCE):
    _ALLOWED.setdefault(stage, set()).update({"PAUSED_BY_USER", "FAILED_SAFE", "WAITING_GPT"})


def transition(current: str, target: str) -> str:
    if target not in _ALLOWED.get(current, set()):
        raise InvalidTransition(f"Invalid XP transition: {current} -> {target}")
    return target


@dataclass(frozen=True)
class TransitionResult:
    current_stage: str
    next_stage: str
    status: str = "CLEAR"
    message: str = ""


@dataclass(frozen=True)
class RemoteSafepointResult:
    local_status: str
    remote_status: str
    message: str


def handle_remote_safepoint(error: Exception | None) -> RemoteSafepointResult:
    if isinstance(error, NetworkUnavailable):
        return RemoteSafepointResult(
            local_status="CLEAR",
            remote_status="REMOTE_UNAVAILABLE",
            message="Local work is clear; remote protection is pending.",
        )
    if error is None:
        return RemoteSafepointResult("CLEAR", "CLEAR", "Remote safepoint created.")
    return RemoteSafepointResult("CLEAR", "ERROR", str(error))


class WorkflowEngine:
    def advance(self, run: RunState) -> TransitionResult:
        if run.stage in PRIMARY_SEQUENCE:
            idx = PRIMARY_SEQUENCE.index(run.stage)
            if idx == len(PRIMARY_SEQUENCE) - 1:
                return TransitionResult(run.stage, run.stage, "KNOWN", "Already locked remotely.")
            target = PRIMARY_SEQUENCE[idx + 1]
            transition(run.stage, target)
            return TransitionResult(run.stage, target)
        raise InvalidTransition(f"Automatic advance unavailable from side state {run.stage}")
