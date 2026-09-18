from __future__ import annotations

import unittest
from datetime import datetime, timezone

from xp.ai.recommendation import (
    FeedbackEvidence,
    RecommendationItem,
    RecommendationReport,
    RecommendationState,
)
from xp.ai.task_feedback import TaskCategory
from xp.ai.usage_history import AIUsageObservation


NOW = datetime(2026, 9, 18, 5, 0, tzinfo=timezone.utc)


class AF04PresentationTests(unittest.TestCase):
    def _module(self):
        import xp.ai.presentation as module
        return module

    def _usage(self, *, tokens=True):
        return AIUsageObservation(
            record_id="record-1",
            timestamp=NOW,
            job_id="job-1",
            route_id="route-a",
            transport="openai-compatible",
            configured_model="configured-model",
            served_model="served-model",
            cost_class="free",
            latency_ms=125.5,
            input_tokens=3 if tokens else None,
            output_tokens=5 if tokens else None,
            total_tokens=8 if tokens else None,
            technical_result="completed",
            error_type=None,
        )

    def _report(self, *, enough_history=False):
        comparable = 5 if enough_history else 2
        item = RecommendationItem(
            route_id="route-a",
            model="model-a",
            state=RecommendationState.CONSIDER,
            comparable_jobs=comparable,
            feedback_jobs=3 if enough_history else 1,
            history_supported=enough_history,
            quality_evidence_supported=enough_history,
            feedback_summary=(
                FeedbackEvidence(good=2, adequate=1, poor=0)
                if enough_history
                else None
            ),
            evidence_notes=(
                ("Gratis.", "Riwayat penggunaan: 5 pekerjaan sejenis.")
                if enough_history
                else ("Gratis.",)
            ),
            limitations=(
                ()
                if enough_history
                else (
                    "Belum cukup data: riwayat penggunaan 2/5 pekerjaan sejenis.",
                    "Belum cukup data feedback: 1/3 pekerjaan sejenis yang dinilai.",
                )
            ),
        )
        return RecommendationReport(
            task_category=TaskCategory.CODING_DEBUGGING,
            headline=(
                "Rekomendasi berbasis bukti XP — lihat jumlah data dan keterbatasan"
                if enough_history
                else "Rekomendasi awal — belum cukup riwayat penggunaan XP"
            ),
            items=(item,),
            requires_user_choice=True,
        )

    def test_cost_labels_are_locked_user_facing_terms(self):
        module = self._module()

        self.assertEqual(module.format_cost_label("free"), "Gratis")
        self.assertEqual(module.format_cost_label("paid"), "Berbayar")
        self.assertEqual(
            module.format_cost_label("unknown"),
            "Biaya belum diketahui",
        )

    def test_missing_tokens_render_tidak_tersedia_not_zero(self):
        module = self._module()

        compact = module.format_usage_compact(self._usage(tokens=False))
        expanded = module.format_usage_expanded(self._usage(tokens=False))

        self.assertIn("Tidak tersedia", compact)
        self.assertIn("Token input: Tidak tersedia", expanded)
        self.assertIn("Token output: Tidak tersedia", expanded)
        self.assertIn("Token total: Tidak tersedia", expanded)

    def test_compact_usage_omits_full_provenance_metadata(self):
        module = self._module()

        text = module.format_usage_compact(self._usage())

        self.assertIn("Gratis", text)
        self.assertIn("configured-model", text)
        self.assertNotIn("Transport:", text)
        self.assertNotIn("Model dilayani:", text)
        self.assertNotIn("Latency:", text)

    def test_expanded_usage_shows_configured_vs_served_model_and_latency(self):
        module = self._module()

        text = module.format_usage_expanded(self._usage())

        self.assertIn("Route: route-a", text)
        self.assertIn("Transport: openai-compatible", text)
        self.assertIn("Model dikonfigurasi: configured-model", text)
        self.assertIn("Model dilayani: served-model", text)
        self.assertIn("Latency: 125.5 ms", text)
        self.assertIn("Token total: 8", text)
        self.assertIn("Biaya: Gratis", text)

    def test_compact_recommendation_shows_limit_without_fake_score(self):
        module = self._module()

        text = module.format_recommendation_compact(self._report())

        self.assertIn("Rekomendasi awal", text)
        self.assertIn("Belum cukup data", text)
        self.assertIn("route-a", text)
        self.assertNotIn("/100", text)
        self.assertNotIn("Winner", text)
        self.assertNotIn("Pemenang", text)

    def test_expanded_recommendation_exposes_evidence_and_limitations(self):
        module = self._module()

        text = module.format_recommendation_expanded(
            self._report(enough_history=True)
        )

        self.assertIn("Bukti:", text)
        self.assertIn("Riwayat penggunaan: 5 pekerjaan sejenis.", text)
        self.assertIn("Feedback pengguna:", text)
        self.assertIn("Bagus 2", text)
        self.assertIn("Pilihan tetap di tangan pengguna.", text)


if __name__ == "__main__":
    unittest.main()
