from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from xp.ai.task_feedback import (
    FeedbackRating,
    JobTaskFeedback,
    TaskCategory,
)
from xp.ai.usage_history import AIUsageObservation
from xp.capabilities import CapabilityState


HISTORY_MIN_JOBS = 5
QUALITY_MIN_FEEDBACK_JOBS = 3


class RecommendationState(str, Enum):
    CONSIDER = "consider"
    REQUIRES_APPROVAL = "requires_approval"
    BLOCKED = "blocked"
    NEEDS_ATTENTION = "needs_attention"
    NOT_CHECKED = "not_checked"
    NOT_SUITABLE = "not_suitable"


@dataclass(frozen=True)
class RecommendationCandidate:
    route_id: str
    model: str
    cost_class: str
    readiness: CapabilityState
    declared_capable: bool = True
    tool_suitable: bool = True

    def __post_init__(self) -> None:
        if not self.route_id:
            raise ValueError("route_id must be non-empty")
        if not self.model:
            raise ValueError("model must be non-empty")
        if self.cost_class not in {"free", "paid", "unknown"}:
            raise ValueError("invalid cost_class")
        if not isinstance(self.readiness, CapabilityState):
            raise ValueError("readiness must be CapabilityState")


@dataclass(frozen=True)
class FeedbackEvidence:
    good: int
    adequate: int
    poor: int


@dataclass(frozen=True)
class RecommendationItem:
    route_id: str
    model: str
    state: RecommendationState
    comparable_jobs: int
    feedback_jobs: int
    history_supported: bool
    quality_evidence_supported: bool
    feedback_summary: FeedbackEvidence | None
    evidence_notes: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class RecommendationReport:
    task_category: TaskCategory
    headline: str
    items: tuple[RecommendationItem, ...]
    requires_user_choice: bool = True


def _candidate_state(
    candidate: RecommendationCandidate,
) -> tuple[RecommendationState, tuple[str, ...]]:
    notes: list[str] = []

    if candidate.cost_class == "paid":
        return (
            RecommendationState.BLOCKED,
            ("Berbayar — diblokir kebijakan zero-cost.",),
        )

    if candidate.readiness is CapabilityState.UNAVAILABLE:
        return (
            RecommendationState.BLOCKED,
            ("Capability tidak tersedia.",),
        )

    if not candidate.declared_capable:
        return (
            RecommendationState.NOT_SUITABLE,
            ("Capability yang dibutuhkan tidak dideklarasikan.",),
        )

    if not candidate.tool_suitable:
        return (
            RecommendationState.NOT_SUITABLE,
            ("Tool yang dibutuhkan tidak cocok dengan route ini.",),
        )

    if candidate.readiness is CapabilityState.NEEDS_ATTENTION:
        return (
            RecommendationState.NEEDS_ATTENTION,
            ("Perlu perhatian — capability belum aman untuk dilanjutkan.",),
        )

    if candidate.readiness is CapabilityState.NOT_CHECKED:
        return (
            RecommendationState.NOT_CHECKED,
            ("Belum diperiksa — tidak dianggap tersedia.",),
        )

    if candidate.cost_class == "unknown":
        return (
            RecommendationState.REQUIRES_APPROVAL,
            (
                "Biaya belum diketahui — perlu persetujuan eksplisit "
                "untuk pekerjaan ini.",
            ),
        )

    notes.append("Gratis.")
    notes.append("Capability tersedia.")
    return RecommendationState.CONSIDER, tuple(notes)


def _comparable_job_ids(
    candidate: RecommendationCandidate,
    task_category: TaskCategory,
    usage_history: Sequence[AIUsageObservation],
    feedback_by_job: Mapping[str, JobTaskFeedback],
) -> tuple[str, ...]:
    job_ids: set[str] = set()

    for record in usage_history:
        if record.job_id is None:
            continue
        if record.route_id != candidate.route_id:
            continue
        if record.configured_model != candidate.model:
            continue

        feedback = feedback_by_job.get(record.job_id)
        if feedback is None:
            continue
        if feedback.task_category is not task_category:
            continue

        job_ids.add(record.job_id)

    return tuple(sorted(job_ids))


def _feedback_evidence(
    job_ids: Sequence[str],
    feedback_by_job: Mapping[str, JobTaskFeedback],
) -> tuple[int, FeedbackEvidence | None]:
    ratings = [
        feedback_by_job[job_id].feedback
        for job_id in job_ids
        if (
            job_id in feedback_by_job
            and feedback_by_job[job_id].feedback
            is not FeedbackRating.UNRATED
        )
    ]

    count = len(ratings)
    if count < QUALITY_MIN_FEEDBACK_JOBS:
        return count, None

    return (
        count,
        FeedbackEvidence(
            good=sum(
                rating is FeedbackRating.GOOD
                for rating in ratings
            ),
            adequate=sum(
                rating is FeedbackRating.ADEQUATE
                for rating in ratings
            ),
            poor=sum(
                rating is FeedbackRating.POOR
                for rating in ratings
            ),
        ),
    )


def recommend(
    task_category: TaskCategory,
    candidates: Sequence[RecommendationCandidate],
    usage_history: Sequence[AIUsageObservation],
    feedback_by_job: Mapping[str, JobTaskFeedback],
) -> RecommendationReport:
    if not isinstance(task_category, TaskCategory):
        task_category = TaskCategory(str(task_category))

    items: list[RecommendationItem] = []

    for candidate in candidates:
        state, state_notes = _candidate_state(candidate)
        job_ids = _comparable_job_ids(
            candidate,
            task_category,
            usage_history,
            feedback_by_job,
        )

        comparable_jobs = len(job_ids)
        history_supported = comparable_jobs >= HISTORY_MIN_JOBS

        feedback_jobs, feedback_summary = _feedback_evidence(
            job_ids,
            feedback_by_job,
        )
        quality_supported = (
            feedback_jobs >= QUALITY_MIN_FEEDBACK_JOBS
        )

        notes = list(state_notes)
        limitations: list[str] = []

        if history_supported:
            notes.append(
                f"Riwayat penggunaan: {comparable_jobs} pekerjaan sejenis."
            )
        else:
            limitations.append(
                "Belum cukup data: riwayat penggunaan "
                f"{comparable_jobs}/{HISTORY_MIN_JOBS} pekerjaan sejenis."
            )

        if quality_supported and feedback_summary is not None:
            notes.append(
                "Feedback pengguna tersedia: "
                f"Bagus {feedback_summary.good}, "
                f"Cukup {feedback_summary.adequate}, "
                f"Kurang sesuai {feedback_summary.poor}."
            )
        else:
            limitations.append(
                "Belum cukup data feedback: "
                f"{feedback_jobs}/{QUALITY_MIN_FEEDBACK_JOBS} "
                "pekerjaan sejenis yang dinilai."
            )

        items.append(
            RecommendationItem(
                route_id=candidate.route_id,
                model=candidate.model,
                state=state,
                comparable_jobs=comparable_jobs,
                feedback_jobs=feedback_jobs,
                history_supported=history_supported,
                quality_evidence_supported=quality_supported,
                feedback_summary=feedback_summary,
                evidence_notes=tuple(notes),
                limitations=tuple(limitations),
            )
        )

    if items and all(
        not item.history_supported
        for item in items
    ):
        headline = (
            "Rekomendasi awal — belum cukup riwayat penggunaan XP"
        )
    else:
        headline = (
            "Rekomendasi berbasis bukti XP — "
            "lihat jumlah data dan keterbatasan"
        )

    return RecommendationReport(
        task_category=task_category,
        headline=headline,
        items=tuple(items),
        requires_user_choice=True,
    )
