from __future__ import annotations

import importlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from xp.ai.contracts import AIRoute


NOW = datetime(2026, 9, 18, 3, 0, tzinfo=timezone.utc)


def route(cost_class: str = "unknown") -> AIRoute:
    return AIRoute(
        route_id="route-1",
        transport="openai-compatible",
        base_url="https://example.invalid/v1",
        model="example/model",
        secret_env="EXAMPLE_KEY",
        cost_class=cost_class,
    )


class AF04CostEvidenceTests(unittest.TestCase):
    def _module(self):
        try:
            return importlib.import_module("xp.ai.cost_evidence")
        except ModuleNotFoundError as exc:
            if exc.name == "xp.ai.cost_evidence":
                self.fail(
                    "xp.ai.cost_evidence must exist for AF-04 Task 4"
                )
            raise

    def test_online_free_evidence_becomes_stale_after_30_days(self):
        module = self._module()
        evidence = module.CostEvidence(
            route_id="route-1",
            observed_cost_class="free",
            verified_at=NOW - timedelta(days=31),
            source="provider-docs",
            scope=module.CostScope.ONLINE,
        )

        self.assertTrue(module.is_stale(evidence, now=NOW))

    def test_online_evidence_at_exactly_30_days_is_not_stale(self):
        module = self._module()
        evidence = module.CostEvidence(
            route_id="route-1",
            observed_cost_class="free",
            verified_at=NOW - timedelta(days=30),
            source="provider-docs",
            scope=module.CostScope.ONLINE,
        )

        self.assertFalse(module.is_stale(evidence, now=NOW))

    def test_stale_online_free_evidence_remains_effectively_free(self):
        module = self._module()
        evidence = module.CostEvidence(
            route_id="route-1",
            observed_cost_class="free",
            verified_at=NOW - timedelta(days=31),
            source="provider-docs",
            scope=module.CostScope.ONLINE,
        )

        self.assertTrue(module.is_stale(evidence, now=NOW))
        self.assertEqual(
            module.effective_cost_class(route("unknown"), evidence),
            "free",
        )

    def test_local_evidence_does_not_expire(self):
        module = self._module()
        evidence = module.CostEvidence(
            route_id="route-1",
            observed_cost_class="free",
            verified_at=NOW - timedelta(days=3650),
            source="local-runtime",
            scope=module.CostScope.LOCAL,
        )

        self.assertFalse(module.is_stale(evidence, now=NOW))

    def test_no_evidence_preserves_declared_cost_class(self):
        module = self._module()

        self.assertEqual(
            module.effective_cost_class(route("paid"), None),
            "paid",
        )
        self.assertEqual(
            module.effective_cost_class(route("unknown"), None),
            "unknown",
        )

    def test_observed_paid_overrides_declared_unknown(self):
        module = self._module()
        evidence = module.CostEvidence(
            route_id="route-1",
            observed_cost_class="paid",
            verified_at=NOW,
            source="provider-docs",
            scope=module.CostScope.ONLINE,
        )

        self.assertEqual(
            module.effective_cost_class(route("unknown"), evidence),
            "paid",
        )

    def test_evidence_round_trips_through_store(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            store = module.CostEvidenceStore.for_home(Path(td))
            evidence = module.CostEvidence(
                route_id="route-1",
                observed_cost_class="free",
                verified_at=NOW,
                source="provider-docs",
                scope=module.CostScope.ONLINE,
            )

            store.put(evidence)

            reopened = module.CostEvidenceStore.for_home(Path(td))
            loaded = reopened.get("route-1")

            self.assertEqual(loaded, evidence)

    def test_store_filename_does_not_embed_raw_route_id(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            store = module.CostEvidenceStore.for_home(Path(td))
            evidence = module.CostEvidence(
                route_id="../../secret route",
                observed_cost_class="free",
                verified_at=NOW,
                source="provider-docs",
                scope=module.CostScope.ONLINE,
            )

            store.put(evidence)

            files = tuple(store.root.glob("*.json"))
            self.assertEqual(len(files), 1)
            self.assertNotIn("secret", files[0].name)
            self.assertNotIn("..", files[0].name)

    def test_store_operations_do_not_access_network(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            store = module.CostEvidenceStore.for_home(Path(td))
            evidence = module.CostEvidence(
                route_id="route-1",
                observed_cost_class="free",
                verified_at=NOW,
                source="provider-docs",
                scope=module.CostScope.ONLINE,
            )

            with patch(
                "urllib.request.urlopen",
                side_effect=AssertionError("network access is forbidden"),
            ):
                store.put(evidence)
                loaded = store.get("route-1")
                stale = module.is_stale(loaded, now=NOW)

            self.assertEqual(loaded, evidence)
            self.assertFalse(stale)


if __name__ == "__main__":
    unittest.main()
