from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from xp.ai.usage_history import AIUsageObservation, UsageHistoryStore


FIXED = datetime(2026, 9, 18, 4, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 18, 4, 5, tzinfo=timezone.utc)


class AF04TaskFeedbackTests(unittest.TestCase):
    def _module(self):
        import xp.ai.task_feedback as module
        return module

    def test_locked_category_labels_are_exact(self):
        module = self._module()

        self.assertEqual(
            module.TASK_CATEGORY_LABELS,
            {
                module.TaskCategory.CODING_DEBUGGING: "Coding / Debugging",
                module.TaskCategory.AUDIT_REVIEW: "Audit / Review",
                module.TaskCategory.ANALYSIS_REASONING: "Analisis / Reasoning",
                module.TaskCategory.RESEARCH_WEB: "Riset / Web",
                module.TaskCategory.DOCUMENT_WRITING: "Dokumen / Writing",
                module.TaskCategory.DATA_SPREADSHEET: "Data / Spreadsheet",
                module.TaskCategory.DESIGN_VISUAL: "Desain / Visual",
                module.TaskCategory.GENERAL: "General",
            },
        )

    def test_locked_feedback_labels_are_exact(self):
        module = self._module()

        self.assertEqual(
            module.FEEDBACK_LABELS,
            {
                module.FeedbackRating.GOOD: "Bagus",
                module.FeedbackRating.ADEQUATE: "Cukup",
                module.FeedbackRating.POOR: "Kurang sesuai",
                module.FeedbackRating.UNRATED: "Belum dinilai",
            },
        )
        self.assertEqual(
            module.FEEDBACK_REASON_LABELS,
            {
                module.FeedbackReason.INACCURATE: "Kurang akurat",
                module.FeedbackReason.INCOMPLETE: "Kurang lengkap",
                module.FeedbackReason.MISUNDERSTOOD: "Salah memahami tugas",
                module.FeedbackReason.TOO_SLOW: "Terlalu lambat",
                module.FeedbackReason.TOOL_ISSUE: "Masalah tool",
                module.FeedbackReason.OTHER: "Lainnya",
            },
        )

    def test_auto_classifier_covers_locked_categories_and_general(self):
        module = self._module()

        cases = (
            ("debug this Python error", module.TaskCategory.CODING_DEBUGGING),
            ("audit and review this control", module.TaskCategory.AUDIT_REVIEW),
            ("analyze the reasoning", module.TaskCategory.ANALYSIS_REASONING),
            ("research the web and cite sources", module.TaskCategory.RESEARCH_WEB),
            ("write a document draft", module.TaskCategory.DOCUMENT_WRITING),
            ("analyze this Excel spreadsheet", module.TaskCategory.DATA_SPREADSHEET),
            ("design a visual poster", module.TaskCategory.DESIGN_VISUAL),
            ("hello there", module.TaskCategory.GENERAL),
        )

        for text, expected in cases:
            with self.subTest(text=text):
                self.assertIs(module.infer_task_category(text), expected)

    def test_auto_category_is_visible_and_user_correction_is_append_only(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            store = module.TaskFeedbackStore.for_home(Path(td))

            auto = store.ensure_auto_category(
                "job-1",
                "debug this Python error",
                when=FIXED,
            )
            self.assertIs(
                auto.task_category,
                module.TaskCategory.CODING_DEBUGGING,
            )
            self.assertIs(
                auto.category_source,
                module.CategorySource.AUTO,
            )
            self.assertEqual(len(auto.category_events), 1)

            corrected = store.set_category(
                "job-1",
                module.TaskCategory.DATA_SPREADSHEET,
                when=LATER,
            )

            self.assertIs(
                corrected.task_category,
                module.TaskCategory.DATA_SPREADSHEET,
            )
            self.assertIs(
                corrected.category_source,
                module.CategorySource.USER,
            )
            self.assertEqual(len(corrected.category_events), 2)
            self.assertIs(
                corrected.category_events[0].new_category,
                module.TaskCategory.CODING_DEBUGGING,
            )
            self.assertIs(
                corrected.category_events[1].previous_category,
                module.TaskCategory.CODING_DEBUGGING,
            )
            self.assertIs(
                corrected.category_events[1].new_category,
                module.TaskCategory.DATA_SPREADSHEET,
            )

            reopened = module.TaskFeedbackStore.for_home(Path(td))
            self.assertEqual(reopened.get("job-1"), corrected)

    def test_auto_category_never_overwrites_user_choice(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            store = module.TaskFeedbackStore.for_home(Path(td))
            store.set_category(
                "job-1",
                module.TaskCategory.AUDIT_REVIEW,
                when=FIXED,
            )

            state = store.ensure_auto_category(
                "job-1",
                "debug this Python error",
                when=LATER,
            )

            self.assertIs(
                state.task_category,
                module.TaskCategory.AUDIT_REVIEW,
            )
            self.assertEqual(len(state.category_events), 1)

    def test_feedback_defaults_to_unrated_and_is_optional(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            store = module.TaskFeedbackStore.for_home(Path(td))
            state = store.get("job-1")

        self.assertIs(
            state.feedback,
            module.FeedbackRating.UNRATED,
        )
        self.assertEqual(state.feedback_reasons, ())
        self.assertEqual(state.feedback_events, ())

    def test_negative_feedback_reasons_are_optional_and_persisted(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            store = module.TaskFeedbackStore.for_home(Path(td))

            poor = store.set_feedback(
                "job-1",
                module.FeedbackRating.POOR,
                reasons=(
                    module.FeedbackReason.INACCURATE,
                    module.FeedbackReason.INCOMPLETE,
                ),
                when=FIXED,
            )

            self.assertIs(
                poor.feedback,
                module.FeedbackRating.POOR,
            )
            self.assertEqual(
                poor.feedback_reasons,
                (
                    module.FeedbackReason.INACCURATE,
                    module.FeedbackReason.INCOMPLETE,
                ),
            )
            self.assertEqual(len(poor.feedback_events), 1)

            reopened = module.TaskFeedbackStore.for_home(Path(td))
            self.assertEqual(reopened.get("job-1"), poor)

    def test_reasons_are_rejected_for_non_negative_feedback(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            store = module.TaskFeedbackStore.for_home(Path(td))

            with self.assertRaises(ValueError):
                store.set_feedback(
                    "job-1",
                    module.FeedbackRating.GOOD,
                    reasons=(module.FeedbackReason.OTHER,),
                    when=FIXED,
                )

    def test_feedback_history_does_not_rewrite_prior_feedback(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            store = module.TaskFeedbackStore.for_home(Path(td))
            store.set_feedback(
                "job-1",
                module.FeedbackRating.ADEQUATE,
                when=FIXED,
            )
            state = store.set_feedback(
                "job-1",
                module.FeedbackRating.GOOD,
                when=LATER,
            )

        self.assertIs(state.feedback, module.FeedbackRating.GOOD)
        self.assertEqual(len(state.feedback_events), 2)
        self.assertIs(
            state.feedback_events[0].new_feedback,
            module.FeedbackRating.ADEQUATE,
        )
        self.assertIs(
            state.feedback_events[1].previous_feedback,
            module.FeedbackRating.ADEQUATE,
        )

    def test_task_feedback_is_independent_from_technical_result(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            usage_store = UsageHistoryStore.for_home(root)
            feedback_store = module.TaskFeedbackStore.for_home(root)

            observation = AIUsageObservation(
                record_id="record-1",
                timestamp=FIXED,
                job_id="job-1",
                route_id="primary",
                transport="fake",
                configured_model="model",
                served_model="model",
                cost_class="free",
                latency_ms=10.0,
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
                technical_result="completed",
                error_type=None,
            )
            usage_store.record(observation)
            before = usage_store.list()

            feedback_store.set_category(
                "job-1",
                module.TaskCategory.AUDIT_REVIEW,
                when=FIXED,
            )
            feedback_store.set_feedback(
                "job-1",
                module.FeedbackRating.POOR,
                reasons=(module.FeedbackReason.MISUNDERSTOOD,),
                when=LATER,
            )

            after = usage_store.list()
            feedback = feedback_store.get("job-1")

        self.assertEqual(before, after)
        self.assertEqual(after[0].technical_result, "completed")
        self.assertIs(
            feedback.feedback,
            module.FeedbackRating.POOR,
        )

    def test_state_filename_hides_raw_job_id_and_store_is_local_only(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = module.TaskFeedbackStore.for_home(root)

            with patch(
                "urllib.request.urlopen",
                side_effect=AssertionError("network access is forbidden"),
            ):
                store.set_category(
                    "../../secret job",
                    module.TaskCategory.GENERAL,
                    when=FIXED,
                )
                loaded = store.get("../../secret job")

            files = tuple(store.root.glob("*.json"))

        self.assertEqual(len(files), 1)
        self.assertNotIn("secret", files[0].name)
        self.assertNotIn("..", files[0].name)
        self.assertIs(loaded.task_category, module.TaskCategory.GENERAL)


if __name__ == "__main__":
    unittest.main()
