import unittest
from datetime import datetime, timezone

from xp.capabilities import (
    CapabilityRegistry,
    CapabilitySnapshot,
    CapabilityState,
)


FIXED = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 17, 10, 30, tzinfo=timezone.utc)


class CapabilityStateTests(unittest.TestCase):
    def test_unchecked_capability_is_not_available(self):
        registry = CapabilityRegistry()

        snapshot = registry.get("live-web")

        self.assertIs(snapshot.state, CapabilityState.NOT_CHECKED)
        self.assertIsNone(snapshot.checked_at)
        self.assertFalse(snapshot.live)

    def test_runtime_failure_downgrades_previous_available_state(self):
        registry = CapabilityRegistry(
            initial=(
                CapabilitySnapshot(
                    capability_id="live-web",
                    state=CapabilityState.AVAILABLE,
                    detail="probe succeeded",
                    checked_at=FIXED,
                    live=True,
                ),
            )
        )

        current = registry.record_runtime_failure(
            "live-web",
            "request failed",
            when=LATER,
        )

        self.assertIs(current.state, CapabilityState.NEEDS_ATTENTION)
        self.assertEqual(current.detail, "request failed")
        self.assertEqual(current.checked_at, LATER)
        self.assertFalse(current.live)

    def test_local_snapshot_never_requires_network(self):
        from unittest.mock import patch

        registry = CapabilityRegistry(
            initial=(
                CapabilitySnapshot(
                    capability_id="git",
                    state=CapabilityState.AVAILABLE,
                    detail="local",
                    checked_at=FIXED,
                    live=False,
                ),
            )
        )

        with patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("network must not run"),
        ):
            snapshots = registry.local_snapshot()

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].capability_id, "git")
        self.assertFalse(snapshots[0].live)


    def test_snapshot_type_is_immutable(self):
        snapshot = CapabilitySnapshot(
            capability_id="git",
            state=CapabilityState.AVAILABLE,
            detail="local",
            checked_at=FIXED,
            live=False,
        )

        with self.assertRaises(Exception):
            snapshot.state = CapabilityState.UNAVAILABLE


    def test_adapter_readiness_maps_to_canonical_snapshots(self):
        from xp.adapters.base import AdapterReadiness, CapabilityAdapter

        class FakeAdapter(CapabilityAdapter):
            def capabilities(self):
                return {"beta-capability", "alpha-capability"}

            def readiness(self):
                return AdapterReadiness(
                    ready=True,
                    status="READY",
                    detail="local runtime ready",
                    capabilities=(
                        "beta-capability",
                        "alpha-capability",
                    ),
                )

        adapter = FakeAdapter()

        self.assertTrue(
            hasattr(adapter, "capability_snapshots"),
            "CapabilityAdapter missing capability_snapshots",
        )

        snapshots = adapter.capability_snapshots()

        self.assertEqual(
            tuple(x.capability_id for x in snapshots),
            ("alpha-capability", "beta-capability"),
        )
        self.assertTrue(
            all(x.state is CapabilityState.AVAILABLE for x in snapshots)
        )
        self.assertTrue(all(x.live is False for x in snapshots))
        self.assertTrue(all(x.checked_at is None for x in snapshots))
        self.assertTrue(
            all(x.metadata["adapter_status"] == "READY" for x in snapshots)
        )

    def test_adapter_readiness_state_mapping_is_explicit(self):
        from xp.adapters.base import AdapterReadiness, CapabilityAdapter

        class FakeAdapter(CapabilityAdapter):
            def __init__(self, status):
                self.status = status

            def capabilities(self):
                return {"demo"}

            def readiness(self):
                return AdapterReadiness(
                    ready=self.status == "READY",
                    status=self.status,
                    detail=self.status,
                    capabilities=("demo",),
                )

        expected = {
            "READY": CapabilityState.AVAILABLE,
            "READY_WITH_LIMITATIONS": CapabilityState.NEEDS_ATTENTION,
            "NOT_READY": CapabilityState.UNAVAILABLE,
        }

        for status, state in expected.items():
            with self.subTest(status=status):
                adapter = FakeAdapter(status)
                self.assertTrue(
                    hasattr(adapter, "capability_snapshots"),
                    "CapabilityAdapter missing capability_snapshots",
                )
                self.assertIs(
                    adapter.capability_snapshots()[0].state,
                    state,
                )

        unknown = FakeAdapter("MYSTERY")
        self.assertTrue(
            hasattr(unknown, "capability_snapshots"),
            "CapabilityAdapter missing capability_snapshots",
        )
        with self.assertRaises(ValueError):
            unknown.capability_snapshots()

    def test_readiness_maps_canonical_snapshot_without_live_probe(self):
        import xp.readiness as readiness

        self.assertTrue(
            hasattr(readiness, "capability_snapshot_to_check"),
            "readiness missing capability_snapshot_to_check",
        )

        cases = (
            (CapabilityState.AVAILABLE, "CLEAR"),
            (CapabilityState.NEEDS_ATTENTION, "WARNING"),
            (CapabilityState.UNAVAILABLE, "BLOCKER"),
            (CapabilityState.NOT_CHECKED, "INFO"),
        )

        for state, expected_level in cases:
            with self.subTest(state=state):
                snapshot = CapabilitySnapshot(
                    capability_id="live-web",
                    state=state,
                    detail="fixture",
                    checked_at=None,
                    live=False,
                )
                check = readiness.capability_snapshot_to_check(snapshot)
                self.assertEqual(check.level, expected_level)
                self.assertEqual(check.code, "CAPABILITY_LIVE_WEB")
                self.assertEqual(check.title, "live-web")
                self.assertEqual(check.detail, "fixture")



if __name__ == "__main__":
    unittest.main()
