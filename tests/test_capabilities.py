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



    def test_live_check_service_is_passive_until_explicit_run(self):
        from xp.capabilities import LiveCheckService, LiveProbe

        calls = []

        def run_probe():
            calls.append("live-web")
            return CapabilitySnapshot(
                capability_id="live-web",
                state=CapabilityState.AVAILABLE,
                detail="reachable",
            )

        registry = CapabilityRegistry()
        LiveCheckService(
            registry,
            probes=(LiveProbe("live-web", run_probe),),
            now=lambda: FIXED,
        )

        self.assertEqual(calls, [])

    def test_explicit_live_check_runs_only_requested_capability_and_stamps_time(self):
        from xp.capabilities import LiveCheckService, LiveProbe

        calls = []

        def web_probe():
            calls.append("live-web")
            return CapabilitySnapshot(
                capability_id="live-web",
                state=CapabilityState.AVAILABLE,
                detail="reachable",
            )

        def ai_probe():
            calls.append("ai")
            return CapabilitySnapshot(
                capability_id="ai",
                state=CapabilityState.AVAILABLE,
                detail="ready",
            )

        registry = CapabilityRegistry()
        service = LiveCheckService(
            registry,
            probes=(
                LiveProbe("live-web", web_probe),
                LiveProbe("ai", ai_probe),
            ),
            now=lambda: FIXED,
        )

        result = service.run_explicit(("live-web",))

        self.assertEqual(calls, ["live-web"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].capability_id, "live-web")
        self.assertEqual(result[0].checked_at, FIXED)
        self.assertTrue(result[0].live)
        self.assertIs(result[0].state, CapabilityState.AVAILABLE)

        stored = registry.get("live-web")
        self.assertEqual(stored.checked_at, FIXED)
        self.assertTrue(stored.live)

    def test_live_probe_exception_becomes_sanitized_needs_attention(self):
        from xp.capabilities import LiveCheckService, LiveProbe

        def broken_probe():
            raise RuntimeError(
                "Authorization: Bearer TOPSECRET api_key=ALSOSECRET"
            )

        registry = CapabilityRegistry()
        service = LiveCheckService(
            registry,
            probes=(LiveProbe("live-web", broken_probe),),
            now=lambda: FIXED,
        )

        result = service.run_explicit(("live-web",))[0]

        self.assertIs(
            result.state,
            CapabilityState.NEEDS_ATTENTION,
        )
        self.assertEqual(result.checked_at, FIXED)
        self.assertTrue(result.live)
        self.assertNotIn("TOPSECRET", result.detail)
        self.assertNotIn("ALSOSECRET", result.detail)
        self.assertIn("RuntimeError", result.detail)



    def test_ai_gateway_exposes_readiness_probe_without_completion(self):
        from xp.ai.contracts import (
            AIRoute,
            AIReadiness,
            AITransport,
        )
        from xp.ai.gateway import AIGateway
        from xp.ai.settings import AISettings
        from xp.capabilities import LiveCheckService

        class FakeTransport(AITransport):
            def __init__(self):
                self.readiness_calls = 0
                self.complete_calls = 0

            def capability_name(self):
                return "fake-ai"

            def readiness(self, route):
                self.readiness_calls += 1
                return AIReadiness(
                    ready=True,
                    status="READY",
                    detail="AI route ready",
                    route_id=route.route_id,
                )

            def complete(self, route, request):
                self.complete_calls += 1
                raise AssertionError(
                    "completion must not run during readiness"
                )

        transport = FakeTransport()

        settings = AISettings(
            version=1,
            default_route="primary",
            routes={
                "primary": AIRoute(
                    route_id="primary",
                    transport="fake",
                    base_url="https://example.invalid/v1",
                    model="test-model",
                    secret_env="TEST_AI_KEY",
                    cost_class="free",
                ),
            },
        )

        gateway = AIGateway(
            settings,
            transports={"fake": transport},
        )

        self.assertTrue(
            hasattr(gateway, "live_readiness_probe"),
            "AIGateway missing live_readiness_probe",
        )

        probe = gateway.live_readiness_probe()

        registry = CapabilityRegistry()
        service = LiveCheckService(
            registry,
            probes=(probe,),
            now=lambda: FIXED,
        )

        result = service.run_explicit(
            (probe.capability_id,)
        )[0]

        self.assertEqual(
            probe.capability_id,
            "ai:primary",
        )
        self.assertEqual(
            transport.readiness_calls,
            1,
        )
        self.assertEqual(
            transport.complete_calls,
            0,
        )
        self.assertIs(
            result.state,
            CapabilityState.AVAILABLE,
        )
        self.assertTrue(result.live)
        self.assertEqual(result.checked_at, FIXED)
        self.assertEqual(
            result.metadata["route_id"],
            "primary",
        )
        self.assertEqual(
            result.metadata["model"],
            "test-model",
        )
        self.assertEqual(
            result.metadata["transport"],
            "fake",
        )

    def test_ai_readiness_probe_does_not_fallback_to_another_route(self):
        from xp.ai.contracts import (
            AIRoute,
            AIReadiness,
            AITransport,
        )
        from xp.ai.gateway import AIGateway
        from xp.ai.settings import AISettings
        from xp.capabilities import LiveCheckService

        class PrimaryTransport(AITransport):
            def __init__(self):
                self.calls = 0

            def capability_name(self):
                return "primary"

            def readiness(self, route):
                self.calls += 1
                return AIReadiness(
                    ready=False,
                    status="NOT_READY",
                    detail="primary unavailable",
                    route_id=route.route_id,
                )

            def complete(self, route, request):
                raise AssertionError(
                    "completion must not run"
                )

        class FallbackTransport(AITransport):
            def __init__(self):
                self.calls = 0

            def capability_name(self):
                return "fallback"

            def readiness(self, route):
                self.calls += 1
                raise AssertionError(
                    "silent fallback is forbidden"
                )

            def complete(self, route, request):
                raise AssertionError(
                    "completion must not run"
                )

        primary = PrimaryTransport()
        fallback = FallbackTransport()

        settings = AISettings(
            version=1,
            default_route="primary",
            routes={
                "primary": AIRoute(
                    route_id="primary",
                    transport="primary",
                    base_url="https://primary.invalid/v1",
                    model="primary-model",
                    secret_env="PRIMARY_KEY",
                    cost_class="free",
                ),
                "fallback": AIRoute(
                    route_id="fallback",
                    transport="fallback",
                    base_url="https://fallback.invalid/v1",
                    model="fallback-model",
                    secret_env="FALLBACK_KEY",
                    cost_class="free",
                ),
            },
        )

        gateway = AIGateway(
            settings,
            transports={
                "primary": primary,
                "fallback": fallback,
            },
        )

        self.assertTrue(
            hasattr(gateway, "live_readiness_probe"),
            "AIGateway missing live_readiness_probe",
        )

        probe = gateway.live_readiness_probe("primary")

        result = LiveCheckService(
            CapabilityRegistry(),
            probes=(probe,),
            now=lambda: FIXED,
        ).run_explicit((probe.capability_id,))[0]

        self.assertEqual(primary.calls, 1)
        self.assertEqual(fallback.calls, 0)
        self.assertIs(
            result.state,
            CapabilityState.NEEDS_ATTENTION,
        )
        self.assertEqual(
            result.metadata["route_id"],
            "primary",
        )



if __name__ == "__main__":
    unittest.main()
