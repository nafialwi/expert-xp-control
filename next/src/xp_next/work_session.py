from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from .job_state import JobState


class WorkAction(str, Enum):
    CONFIRM_WORKER = "CONFIRM_WORKER"
    DECLINE_WORKER = "DECLINE_WORKER"
    APPROVE_SANDBOX = "APPROVE_SANDBOX"
    DECLINE_SANDBOX = "DECLINE_SANDBOX"
    EXECUTE = "EXECUTE"
    APPLY = "APPLY"
    DISCARD = "DISCARD"


_STATE_LABELS: dict[JobState, str] = {
    JobState.DRAFT: "Belum dimulai",
    JobState.PLANNING: "Menyiapkan pekerjaan",
    JobState.READY: "Siap dilanjutkan",
    JobState.AWAITING_APPROVAL: "Menunggu persetujuan Anda",
    JobState.RUNNING: "Sedang bekerja",
    JobState.VERIFYING: "Memeriksa hasil",
    JobState.READY_TO_REVIEW: "Hasil siap diperiksa",
    JobState.APPLYING: "Menerapkan hasil",
    JobState.VERIFYING_APPLIED: "Memeriksa hasil terapan",
    JobState.COMPLETED: "Selesai",
    JobState.NEEDS_ATTENTION: "Perlu perhatian",
    JobState.ROLLED_BACK: "Dikembalikan ke kondisi aman",
    JobState.CANCELLED: "Dibatalkan",
}


def allowed_actions(
    state: JobState,
    payload: Mapping[str, object],
) -> tuple[WorkAction, ...]:
    if state is JobState.AWAITING_APPROVAL:
        confirmation = payload.get("worker_confirmation")
        if not isinstance(confirmation, Mapping):
            return (
                WorkAction.CONFIRM_WORKER,
                WorkAction.DECLINE_WORKER,
            )
        if confirmation.get("status") != "CONFIRMED":
            return ()
        if payload.get("sandbox_approved") is None:
            return (
                WorkAction.APPROVE_SANDBOX,
                WorkAction.DECLINE_SANDBOX,
            )
        if payload.get("sandbox_approved") is True:
            return (WorkAction.EXECUTE,)
        return ()

    if state is JobState.READY_TO_REVIEW:
        review = payload.get("review")
        if isinstance(review, Mapping) and review.get("status") == "PASS":
            return (WorkAction.APPLY, WorkAction.DISCARD)

    return ()


@dataclass(frozen=True)
class WorkSessionSnapshot:
    job: dict[str, object]
    session: dict[str, object]
    activities: tuple[dict[str, object], ...]

    @property
    def state(self) -> JobState:
        return JobState(str(self.job["state"]))

    @property
    def revision(self) -> int:
        return int(self.session["revision"])

    @property
    def payload(self) -> dict[str, object]:
        value = self.session["payload"]
        if not isinstance(value, dict):
            raise ValueError("session payload must be an object")
        return value

    @property
    def allowed_actions(self) -> tuple[WorkAction, ...]:
        return allowed_actions(self.state, self.payload)


def _public_worker(payload: Mapping[str, object]) -> dict[str, object] | None:
    selection = payload.get("worker_selection")
    if not isinstance(selection, Mapping):
        return None

    result: dict[str, object] = {
        "status": selection.get("status"),
        "backend_id": selection.get("backend_id"),
        "detail": selection.get("detail"),
    }

    resources = selection.get("resource_snapshot")
    if isinstance(resources, Mapping):
        result["resources"] = {
            "available_memory_mb": resources.get("available_memory_mb"),
            "logical_cpus": resources.get("logical_cpus"),
            "source": resources.get("source"),
        }

    confirmation = payload.get("worker_confirmation")
    if isinstance(confirmation, Mapping):
        result["confirmation"] = {
            "status": confirmation.get("status"),
            "backend_id": confirmation.get("backend_id"),
            "detail": confirmation.get("detail"),
        }

    return result


def _public_review(payload: Mapping[str, object]) -> dict[str, object] | None:
    review = payload.get("review")
    if not isinstance(review, Mapping):
        return None
    changed_files = review.get("changed_files")
    return {
        "status": review.get("status"),
        "summary": review.get("summary"),
        "changed_files": list(changed_files) if isinstance(changed_files, (list, tuple)) else [],
        "changed_file_count": (
            len(changed_files) if isinstance(changed_files, (list, tuple)) else 0
        ),
        "bounded_diff": review.get("bounded_diff"),
        "diff_truncated": bool(review.get("diff_truncated", False)),
        "change_fingerprint": review.get("change_fingerprint"),
    }


def _public_activities(
    activities: tuple[dict[str, object], ...],
) -> list[dict[str, object]]:
    return [
        {
            "action": row.get("action"),
            "status": row.get("status"),
            "summary": row.get("summary"),
            "source": row.get("source"),
            "processor": row.get("processor"),
            "live": bool(row.get("live", False)),
            "created_at": row.get("created_at"),
        }
        for row in activities
    ]


def public_session(snapshot: WorkSessionSnapshot) -> dict[str, object]:
    payload = snapshot.payload
    return {
        "id": snapshot.job["id"],
        "project": {
            "id": snapshot.job["project_id"],
            "name": payload.get("project_name"),
        },
        "goal": snapshot.job["user_goal"],
        "state": snapshot.state.value,
        "state_label": _STATE_LABELS[snapshot.state],
        "revision": snapshot.revision,
        "worker": _public_worker(payload),
        "sandbox": {
            "approved": payload.get("sandbox_approved"),
        },
        "review": _public_review(payload),
        "apply_status": payload.get("apply_status"),
        "recovery_available": bool(payload.get("recovery_ref")),
        "allowed_actions": [action.value for action in snapshot.allowed_actions],
        "activities": _public_activities(snapshot.activities),
    }
