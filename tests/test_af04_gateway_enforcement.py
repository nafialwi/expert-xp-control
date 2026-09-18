from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xp.activity import ActivityStatus
from xp.ai.contracts import (
    AIRequest,
    AIResponse,
    AIUsage,
)
from xp.ai.gateway import AIGateway
from xp.ai.job_state import JobAIStateStore
from xp.ai.settings import AISettings


class CountingTransport:
    def __init__(self):
        self.complete_calls = []

    def capability_name(self):
        return "counting"

    def readiness(self, route):
        raise AssertionError(
            "readiness must not be called by complete()"
        )

    def complete(self, route, request):
        self.complete_calls.append((route.route_id, request))
        return AIResponse(
            route_id=route.route_id,
            model=route.model,
            text="ok",
            tool_calls=(),
            usage=AIUsage(),
            finish_reason="stop",
        )


class ListRecorder:
    def __init__(self):
        self.events = []

    def record(self, event):
        self.events.append(event)


def make_settings() -> AISettings:
    return AISettings.from_dict(
        {
            "version": 1,
            "default_route": "free",
            "routes": {
                "free": {
                    "transport": "free-transport",
                    "base_url": "https://free.invalid/v1",
                    "model": "model-free",
                    "secret_env": "FREE_KEY",
                    "cost_class": "free",
                },
                "paid": {
                    "transport": "paid-transport",
                    "base_url": "https://paid.invalid/v1",
                    "model": "model-paid",
                    "secret_env": "PAID_KEY",
                    "cost_class": "paid",
                },
                "unknown": {
                    "transport": "unknown-transport",
                    "base_url": "https://unknown.invalid/v1",
                    "model": "model-unknown",
                    "secret_env": "UNKNOWN_KEY",
                    "cost_class": "unknown",
                },
            },
        }
    )


REQUEST = AIRequest(
    messages=(
        {"role": "user", "content": "test"},
    )
)


class AF04GatewayEnforcementTests(unittest.TestCase):
    def _assert_policy_blocked(self, callable_):
        try:
            callable_()
        except Exception as exc:
            self.assertEqual(
                type(exc).__name__,
                "AIPolicyBlockedError",
            )
            return exc
        self.fail("AF-04 policy should have blocked the request")

    def test_paid_route_never_reaches_transport(self):
        paid = CountingTransport()
        gateway = AIGateway(
            make_settings(),
            transports={
                "free-transport": CountingTransport(),
                "paid-transport": paid,
                "unknown-transport": CountingTransport(),
            },
        )

        self._assert_policy_blocked(
            lambda: gateway.complete(
                REQUEST,
                route_id="paid",
                job_id="job-paid",
            )
        )

        self.assertEqual(paid.complete_calls, [])

    def test_unknown_route_without_job_approval_never_reaches_transport(self):
        unknown = CountingTransport()

        with tempfile.TemporaryDirectory() as td:
            store = JobAIStateStore.for_home(Path(td))
            gateway = AIGateway(
                make_settings(),
                transports={
                    "free-transport": CountingTransport(),
                    "paid-transport": CountingTransport(),
                    "unknown-transport": unknown,
                },
                job_state_store=store,
            )

            self._assert_policy_blocked(
                lambda: gateway.complete(
                    REQUEST,
                    route_id="unknown",
                    job_id="job-unknown",
                )
            )

        self.assertEqual(unknown.complete_calls, [])

    def test_unknown_route_with_exact_job_route_model_approval_executes(self):
        unknown = CountingTransport()

        with tempfile.TemporaryDirectory() as td:
            store = JobAIStateStore.for_home(Path(td))
            store.approve_unknown(
                "job-unknown",
                "unknown",
                "model-unknown",
            )

            gateway = AIGateway(
                make_settings(),
                transports={
                    "free-transport": CountingTransport(),
                    "paid-transport": CountingTransport(),
                    "unknown-transport": unknown,
                },
                job_state_store=store,
            )

            response = gateway.complete(
                REQUEST,
                route_id="unknown",
                job_id="job-unknown",
            )

        self.assertEqual(response.route_id, "unknown")
        self.assertEqual(len(unknown.complete_calls), 1)

    def test_unknown_approval_for_different_model_does_not_authorize(self):
        unknown = CountingTransport()

        with tempfile.TemporaryDirectory() as td:
            store = JobAIStateStore.for_home(Path(td))
            store.approve_unknown(
                "job-unknown",
                "unknown",
                "different-model",
            )

            gateway = AIGateway(
                make_settings(),
                transports={
                    "free-transport": CountingTransport(),
                    "paid-transport": CountingTransport(),
                    "unknown-transport": unknown,
                },
                job_state_store=store,
            )

            self._assert_policy_blocked(
                lambda: gateway.complete(
                    REQUEST,
                    route_id="unknown",
                    job_id="job-unknown",
                )
            )

        self.assertEqual(unknown.complete_calls, [])

    def test_free_route_executes_normally(self):
        free = CountingTransport()
        gateway = AIGateway(
            make_settings(),
            transports={
                "free-transport": free,
                "paid-transport": CountingTransport(),
                "unknown-transport": CountingTransport(),
            },
        )

        response = gateway.complete(
            REQUEST,
            route_id="free",
            job_id="job-free",
        )

        self.assertEqual(response.route_id, "free")
        self.assertEqual(len(free.complete_calls), 1)

    def test_blocked_policy_is_observable_without_prompt_content(self):
        paid = CountingTransport()
        recorder = ListRecorder()

        gateway = AIGateway(
            make_settings(),
            transports={
                "free-transport": CountingTransport(),
                "paid-transport": paid,
                "unknown-transport": CountingTransport(),
            },
            activity_recorder=recorder,
            activity_job_id="job-paid",
        )

        self._assert_policy_blocked(
            lambda: gateway.complete(
                REQUEST,
                route_id="paid",
                job_id="job-paid",
            )
        )

        self.assertEqual(paid.complete_calls, [])
        self.assertEqual(len(recorder.events), 1)

        event = recorder.events[0]
        self.assertIs(event.status, ActivityStatus.FAILED)
        self.assertEqual(event.action, "AI policy")
        self.assertEqual(
            event.metadata["policy_decision"],
            "BLOCK",
        )
        self.assertEqual(
            event.metadata["cost_class"],
            "paid",
        )

        rendered = repr(event)
        self.assertNotIn("test", rendered)
        self.assertNotIn("PAID_KEY", rendered)


if __name__ == "__main__":
    unittest.main()
