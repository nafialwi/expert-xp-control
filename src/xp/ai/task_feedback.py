from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Mapping

from xp.paths import ai_state_root


class TaskFeedbackError(RuntimeError):
    pass


class TaskCategory(str, Enum):
    CODING_DEBUGGING = "coding_debugging"
    AUDIT_REVIEW = "audit_review"
    ANALYSIS_REASONING = "analysis_reasoning"
    RESEARCH_WEB = "research_web"
    DOCUMENT_WRITING = "document_writing"
    DATA_SPREADSHEET = "data_spreadsheet"
    DESIGN_VISUAL = "design_visual"
    GENERAL = "general"


TASK_CATEGORY_LABELS = {
    TaskCategory.CODING_DEBUGGING: "Coding / Debugging",
    TaskCategory.AUDIT_REVIEW: "Audit / Review",
    TaskCategory.ANALYSIS_REASONING: "Analisis / Reasoning",
    TaskCategory.RESEARCH_WEB: "Riset / Web",
    TaskCategory.DOCUMENT_WRITING: "Dokumen / Writing",
    TaskCategory.DATA_SPREADSHEET: "Data / Spreadsheet",
    TaskCategory.DESIGN_VISUAL: "Desain / Visual",
    TaskCategory.GENERAL: "General",
}


class CategorySource(str, Enum):
    AUTO = "auto"
    USER = "user"


class FeedbackRating(str, Enum):
    GOOD = "good"
    ADEQUATE = "adequate"
    POOR = "poor"
    UNRATED = "unrated"


FEEDBACK_LABELS = {
    FeedbackRating.GOOD: "Bagus",
    FeedbackRating.ADEQUATE: "Cukup",
    FeedbackRating.POOR: "Kurang sesuai",
    FeedbackRating.UNRATED: "Belum dinilai",
}


class FeedbackReason(str, Enum):
    INACCURATE = "inaccurate"
    INCOMPLETE = "incomplete"
    MISUNDERSTOOD = "misunderstood"
    TOO_SLOW = "too_slow"
    TOOL_ISSUE = "tool_issue"
    OTHER = "other"


FEEDBACK_REASON_LABELS = {
    FeedbackReason.INACCURATE: "Kurang akurat",
    FeedbackReason.INCOMPLETE: "Kurang lengkap",
    FeedbackReason.MISUNDERSTOOD: "Salah memahami tugas",
    FeedbackReason.TOO_SLOW: "Terlalu lambat",
    FeedbackReason.TOOL_ISSUE: "Masalah tool",
    FeedbackReason.OTHER: "Lainnya",
}


@dataclass(frozen=True)
class CategoryEvent:
    previous_category: TaskCategory | None
    new_category: TaskCategory
    source: CategorySource
    timestamp: datetime


@dataclass(frozen=True)
class FeedbackEvent:
    previous_feedback: FeedbackRating
    new_feedback: FeedbackRating
    reasons: tuple[FeedbackReason, ...]
    timestamp: datetime


@dataclass(frozen=True)
class JobTaskFeedback:
    job_id: str
    task_category: TaskCategory = TaskCategory.GENERAL
    category_source: CategorySource | None = None
    category_events: tuple[CategoryEvent, ...] = ()
    feedback: FeedbackRating = FeedbackRating.UNRATED
    feedback_reasons: tuple[FeedbackReason, ...] = ()
    feedback_events: tuple[FeedbackEvent, ...] = ()


def _aware(when: datetime | None) -> datetime:
    value = when or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


def infer_task_category(text: str) -> TaskCategory:
    normalized = " ".join(str(text).lower().split())

    keyword_groups = (
        (
            TaskCategory.DATA_SPREADSHEET,
            ("spreadsheet", "excel", "csv", "workbook", "worksheet"),
        ),
        (
            TaskCategory.DESIGN_VISUAL,
            ("design", "visual", "poster", "logo", "image", "gambar"),
        ),
        (
            TaskCategory.CODING_DEBUGGING,
            (
                "debug",
                "error",
                "bug",
                "python",
                "javascript",
                "typescript",
                "stack trace",
                "source code",
                "kode",
            ),
        ),
        (
            TaskCategory.AUDIT_REVIEW,
            ("audit", "review", "inspect", "compliance", "kontrol"),
        ),
        (
            TaskCategory.RESEARCH_WEB,
            ("research", "riset", "web", "search", "source", "cite", "sumber"),
        ),
        (
            TaskCategory.DOCUMENT_WRITING,
            ("document", "dokumen", "write", "writing", "draft", "word", "report"),
        ),
        (
            TaskCategory.ANALYSIS_REASONING,
            ("analyze", "analysis", "analisis", "reasoning", "reason"),
        ),
    )

    for category, keywords in keyword_groups:
        if any(keyword in normalized for keyword in keywords):
            return category

    return TaskCategory.GENERAL


class TaskFeedbackStore:
    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()

    @classmethod
    def for_home(cls, home: Path) -> "TaskFeedbackStore":
        return cls(ai_state_root(home) / "task-feedback")

    def _path_for(self, job_id: str) -> Path:
        if not isinstance(job_id, str) or not job_id:
            raise ValueError("job_id must be a non-empty string")
        digest = hashlib.sha256(job_id.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    def _empty(self, job_id: str) -> JobTaskFeedback:
        return JobTaskFeedback(job_id=job_id)

    def get(self, job_id: str) -> JobTaskFeedback:
        path = self._path_for(job_id)
        if not path.exists():
            return self._empty(job_id)

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TaskFeedbackError(
                "Unable to read task feedback state"
            ) from exc

        if not isinstance(raw, Mapping):
            raise TaskFeedbackError(
                "Persisted task feedback state must be an object"
            )

        if raw.get("job_id") != job_id:
            raise TaskFeedbackError(
                "Persisted task feedback job_id mismatch"
            )

        try:
            category_events = tuple(
                CategoryEvent(
                    previous_category=(
                        None
                        if item.get("previous_category") is None
                        else TaskCategory(str(item["previous_category"]))
                    ),
                    new_category=TaskCategory(str(item["new_category"])),
                    source=CategorySource(str(item["source"])),
                    timestamp=datetime.fromisoformat(str(item["timestamp"])),
                )
                for item in raw.get("category_events", [])
            )
            feedback_events = tuple(
                FeedbackEvent(
                    previous_feedback=FeedbackRating(
                        str(item["previous_feedback"])
                    ),
                    new_feedback=FeedbackRating(str(item["new_feedback"])),
                    reasons=tuple(
                        FeedbackReason(str(reason))
                        for reason in item.get("reasons", [])
                    ),
                    timestamp=datetime.fromisoformat(str(item["timestamp"])),
                )
                for item in raw.get("feedback_events", [])
            )

            return JobTaskFeedback(
                job_id=job_id,
                task_category=TaskCategory(
                    str(raw.get("task_category", TaskCategory.GENERAL.value))
                ),
                category_source=(
                    None
                    if raw.get("category_source") is None
                    else CategorySource(str(raw["category_source"]))
                ),
                category_events=category_events,
                feedback=FeedbackRating(
                    str(raw.get("feedback", FeedbackRating.UNRATED.value))
                ),
                feedback_reasons=tuple(
                    FeedbackReason(str(reason))
                    for reason in raw.get("feedback_reasons", [])
                ),
                feedback_events=feedback_events,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TaskFeedbackError(
                "Persisted task feedback state is invalid"
            ) from exc

    def save(self, state: JobTaskFeedback) -> None:
        path = self._path_for(state.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "job_id": state.job_id,
            "task_category": state.task_category.value,
            "category_source": (
                None
                if state.category_source is None
                else state.category_source.value
            ),
            "category_events": [
                {
                    "previous_category": (
                        None
                        if event.previous_category is None
                        else event.previous_category.value
                    ),
                    "new_category": event.new_category.value,
                    "source": event.source.value,
                    "timestamp": event.timestamp.isoformat(),
                }
                for event in state.category_events
            ],
            "feedback": state.feedback.value,
            "feedback_reasons": [
                reason.value for reason in state.feedback_reasons
            ],
            "feedback_events": [
                {
                    "previous_feedback": event.previous_feedback.value,
                    "new_feedback": event.new_feedback.value,
                    "reasons": [reason.value for reason in event.reasons],
                    "timestamp": event.timestamp.isoformat(),
                }
                for event in state.feedback_events
            ],
        }

        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"

        temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        try:
            temp.write_text(encoded, encoding="utf-8")
            temp.replace(path)
        except OSError as exc:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            raise TaskFeedbackError(
                "Unable to persist task feedback state"
            ) from exc

    def ensure_auto_category(
        self,
        job_id: str,
        text: str,
        *,
        when: datetime | None = None,
    ) -> JobTaskFeedback:
        current = self.get(job_id)
        if current.category_events:
            return current

        category = infer_task_category(text)
        timestamp = _aware(when)
        state = replace(
            current,
            task_category=category,
            category_source=CategorySource.AUTO,
            category_events=(
                CategoryEvent(
                    previous_category=None,
                    new_category=category,
                    source=CategorySource.AUTO,
                    timestamp=timestamp,
                ),
            ),
        )
        self.save(state)
        return state

    def set_category(
        self,
        job_id: str,
        category: TaskCategory,
        *,
        when: datetime | None = None,
    ) -> JobTaskFeedback:
        if not isinstance(category, TaskCategory):
            category = TaskCategory(str(category))

        current = self.get(job_id)
        timestamp = _aware(when)
        previous = None if not current.category_events else current.task_category

        state = replace(
            current,
            task_category=category,
            category_source=CategorySource.USER,
            category_events=current.category_events
            + (
                CategoryEvent(
                    previous_category=previous,
                    new_category=category,
                    source=CategorySource.USER,
                    timestamp=timestamp,
                ),
            ),
        )
        self.save(state)
        return state

    def set_feedback(
        self,
        job_id: str,
        feedback: FeedbackRating,
        *,
        reasons: tuple[FeedbackReason, ...] = (),
        when: datetime | None = None,
    ) -> JobTaskFeedback:
        if not isinstance(feedback, FeedbackRating):
            feedback = FeedbackRating(str(feedback))

        normalized_reasons = tuple(
            reason
            if isinstance(reason, FeedbackReason)
            else FeedbackReason(str(reason))
            for reason in reasons
        )

        if feedback is not FeedbackRating.POOR and normalized_reasons:
            raise ValueError(
                "feedback reasons are only valid for negative feedback"
            )

        timestamp = _aware(when)
        current = self.get(job_id)

        state = replace(
            current,
            feedback=feedback,
            feedback_reasons=normalized_reasons,
            feedback_events=current.feedback_events
            + (
                FeedbackEvent(
                    previous_feedback=current.feedback,
                    new_feedback=feedback,
                    reasons=normalized_reasons,
                    timestamp=timestamp,
                ),
            ),
        )
        self.save(state)
        return state
