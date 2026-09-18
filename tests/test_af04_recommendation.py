from __future__ import annotations

import unittest
from dataclasses import fields
from datetime import datetime, timezone

from xp.ai.task_feedback import (
    FeedbackRating,
    JobTaskFeedback,
    TaskCategory,
)
from xp.ai.usage_history import AIUsageObservation
from xp.capabilities import CapabilityState


NOW = datetime(2026, 9, 18, 4, 15, tzinfo=timezone.utc)


class AF04RecommendationTests(unittest.TestCase):
    def _module(self):
        import xp.ai.recommendation as module
        return module

    def _candidate(
        self,
        *,
        route_id="route-a",
        model="model-a",
        cost_class="free",
        readiness=CapabilityState.AVAILABLE,
        declared_capable=True,
        tool_suitable=True,
    ):
        module = self._module()
        return module.RecommendationCandidate(
            route_id=route_id,
            model=model,
            cost_class=cost_class,
            readiness=readiness,
            declared_capable=declared_capable,
            tool_suitable=tool_suitable,
        )

    @staticmethod
    def _usage(
        job_id,
        *,
        route_id="route-a",
        model="model-a",
        result="completed",
    ):
        return AIUsageObservation(
            record_id=f"record-{job_id}",
            timestamp=NOW,
            job_id=job_id,
            route_id=route_id,
            transport="fake",
            configured_model=model,
            served_model=model,
            cost_class="free",
            latency_ms=10.0,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            technical_result=result,
            error_type=None,
        )

    @staticmethod
    def _feedback(
        job_id,
        *,
        category=TaskCategory.CODING_DEBUGGING,
        rating=FeedbackRating.UNRATED,
    ):
        return JobTaskFeedback(
            job_id=job_id,
            task_category=category,
            feedback=rating,
        )

    def test_zero_to_four_jobs_is_initial_recommendation_only(self):
        module = self._module()

        usage = tuple(self._usage(f"job-{i}") for i in range(4))
        feedback = {
            f"job-{i}": self._feedback(f"job-{i}")
            for i in range(4)
        }

        report = module.recommend(
            TaskCategory.CODING_DEBUGGING,
            (self._candidate(),),
            usage,
            feedback,
        )

        self.assertEqual(
            report.headline,
            "Rekomendasi awal — belum cukup riwayat penggunaan XP",
        )
        item = report.items[0]
        self.assertEqual(item.comparable_jobs, 4)
        self.assertFalse(item.history_supported)
        self.assertIn("4/5", " ".join(item.limitations))
        self.assertTrue(report.requires_user_choice)

    def test_five_comparable_jobs_allow_history_evidence(self):
        module = self._module()

        usage = tuple(self._usage(f"job-{i}") for i in range(5))
        feedback = {
            f"job-{i}": self._feedback(f"job-{i}")
            for i in range(5)
        }

        report = module.recommend(
            TaskCategory.CODING_DEBUGGING,
            (self._candidate(),),
            usage,
            feedback,
        )

        item = report.items[0]
        self.assertEqual(item.comparable_jobs, 5)
        self.assertTrue(item.history_supported)
        self.assertIn("5 pekerjaan sejenis", " ".join(item.evidence_notes))

    def test_comparable_jobs_are_unique_jobs_not_request_count(self):
        module = self._module()

        usage = (
            self._usage("job-1"),
            AIUsageObservation(
                record_id="record-job-1-second",
                timestamp=NOW,
                job_id="job-1",
                route_id="route-a",
                transport="fake",
                configured_model="model-a",
                served_model="model-a",
                cost_class="free",
                latency_ms=12.0,
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
                technical_result="completed",
                error_type=None,
            ),
        )
        feedback = {
            "job-1": self._feedback("job-1"),
        }

        report = module.recommend(
            TaskCategory.CODING_DEBUGGING,
            (self._candidate(),),
            usage,
            feedback,
        )

        self.assertEqual(report.items[0].comparable_jobs, 1)

    def test_jobs_from_other_category_are_not_comparable(self):
        module = self._module()

        usage = (self._usage("job-1"), self._usage("job-2"))
        feedback = {
            "job-1": self._feedback(
                "job-1",
                category=TaskCategory.CODING_DEBUGGING,
            ),
            "job-2": self._feedback(
                "job-2",
                category=TaskCategory.AUDIT_REVIEW,
            ),
        }

        report = module.recommend(
            TaskCategory.CODING_DEBUGGING,
            (self._candidate(),),
            usage,
            feedback,
        )

        self.assertEqual(report.items[0].comparable_jobs, 1)

    def test_quality_claim_requires_three_feedback_bearing_jobs(self):
        module = self._module()

        usage = tuple(self._usage(f"job-{i}") for i in range(5))
        feedback = {
            "job-0": self._feedback(
                "job-0",
                rating=FeedbackRating.GOOD,
            ),
            "job-1": self._feedback(
                "job-1",
                rating=FeedbackRating.POOR,
            ),
            "job-2": self._feedback("job-2"),
            "job-3": self._feedback("job-3"),
            "job-4": self._feedback("job-4"),
        }

        report = module.recommend(
            TaskCategory.CODING_DEBUGGING,
            (self._candidate(),),
            usage,
            feedback,
        )
        item = report.items[0]

        self.assertEqual(item.feedback_jobs, 2)
        self.assertFalse(item.quality_evidence_supported)
        self.assertIsNone(item.feedback_summary)
        self.assertIn("2/3", " ".join(item.limitations))

    def test_three_feedback_jobs_expose_counts_not_score(self):
        module = self._module()

        usage = tuple(self._usage(f"job-{i}") for i in range(5))
        feedback = {
            "job-0": self._feedback(
                "job-0",
                rating=FeedbackRating.GOOD,
            ),
            "job-1": self._feedback(
                "job-1",
                rating=FeedbackRating.ADEQUATE,
            ),
            "job-2": self._feedback(
                "job-2",
                rating=FeedbackRating.POOR,
            ),
            "job-3": self._feedback("job-3"),
            "job-4": self._feedback("job-4"),
        }

        report = module.recommend(
            TaskCategory.CODING_DEBUGGING,
            (self._candidate(),),
            usage,
            feedback,
        )
        item = report.items[0]

        self.assertEqual(item.feedback_jobs, 3)
        self.assertTrue(item.quality_evidence_supported)
        self.assertEqual(
            item.feedback_summary,
            module.FeedbackEvidence(
                good=1,
                adequate=1,
                poor=1,
            ),
        )

        forbidden = {
            "score",
            "rank",
            "winner",
            "selected_route_id",
            "best_model",
        }
        report_fields = {field.name for field in fields(type(report))}
        item_fields = {field.name for field in fields(type(item))}
        self.assertTrue(forbidden.isdisjoint(report_fields))
        self.assertTrue(forbidden.isdisjoint(item_fields))

    def test_paid_route_is_hard_blocked_from_consideration(self):
        module = self._module()

        report = module.recommend(
            TaskCategory.GENERAL,
            (self._candidate(cost_class="paid"),),
            (),
            {},
        )

        item = report.items[0]
        self.assertIs(
            item.state,
            module.RecommendationState.BLOCKED,
        )
        self.assertIn("Berbayar", " ".join(item.evidence_notes))

    def test_unknown_cost_requires_approval_not_silent_allow(self):
        module = self._module()

        report = module.recommend(
            TaskCategory.GENERAL,
            (self._candidate(cost_class="unknown"),),
            (),
            {},
        )

        self.assertIs(
            report.items[0].state,
            module.RecommendationState.REQUIRES_APPROVAL,
        )
        self.assertIn(
            "Biaya belum diketahui",
            " ".join(report.items[0].evidence_notes),
        )

    def test_not_checked_is_not_available(self):
        module = self._module()

        report = module.recommend(
            TaskCategory.GENERAL,
            (
                self._candidate(
                    readiness=CapabilityState.NOT_CHECKED,
                ),
            ),
            (),
            {},
        )

        self.assertIs(
            report.items[0].state,
            module.RecommendationState.NOT_CHECKED,
        )

    def test_needs_attention_remains_visible(self):
        module = self._module()

        report = module.recommend(
            TaskCategory.GENERAL,
            (
                self._candidate(
                    readiness=CapabilityState.NEEDS_ATTENTION,
                ),
            ),
            (),
            {},
        )

        self.assertIs(
            report.items[0].state,
            module.RecommendationState.NEEDS_ATTENTION,
        )
        self.assertIn(
            "Perlu perhatian",
            " ".join(report.items[0].evidence_notes),
        )

    def test_unavailable_or_unsuitable_is_not_recommended(self):
        module = self._module()

        report = module.recommend(
            TaskCategory.GENERAL,
            (
                self._candidate(
                    route_id="unavailable",
                    readiness=CapabilityState.UNAVAILABLE,
                ),
                self._candidate(
                    route_id="tool-mismatch",
                    tool_suitable=False,
                ),
                self._candidate(
                    route_id="not-capable",
                    declared_capable=False,
                ),
            ),
            (),
            {},
        )

        self.assertIs(
            report.items[0].state,
            module.RecommendationState.BLOCKED,
        )
        self.assertIs(
            report.items[1].state,
            module.RecommendationState.NOT_SUITABLE,
        )
        self.assertIs(
            report.items[2].state,
            module.RecommendationState.NOT_SUITABLE,
        )

    def test_free_available_suitable_candidate_is_only_considered(self):
        module = self._module()

        report = module.recommend(
            TaskCategory.GENERAL,
            (self._candidate(),),
            (),
            {},
        )

        self.assertIs(
            report.items[0].state,
            module.RecommendationState.CONSIDER,
        )
        self.assertTrue(report.requires_user_choice)

    def test_candidate_order_is_preserved_and_engine_does_not_rank(self):
        module = self._module()

        candidates = (
            self._candidate(route_id="route-b", model="model-b"),
            self._candidate(route_id="route-a", model="model-a"),
        )

        report = module.recommend(
            TaskCategory.GENERAL,
            candidates,
            (),
            {},
        )

        self.assertEqual(
            tuple(item.route_id for item in report.items),
            ("route-b", "route-a"),
        )
        self.assertTrue(report.requires_user_choice)


if __name__ == "__main__":
    unittest.main()
