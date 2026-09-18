from __future__ import annotations

import dataclasses
import unittest
from datetime import datetime, timezone

from xp.ai import contracts as ai_contracts
from xp.ai.agents import AgentRunRequest
from xp.ai.agents.live_readiness import (
    LiveHTTPResult,
    LiveReadinessPermissionError,
)
from xp.ai.agents.live_wiring import (
    build_default_zero_cost_live_wiring,
    build_live_local_agent_wiring,
)
from xp.ai.agents.local_backends import LOCAL_QWEN, ROUTER_9


FIXED_TIME = datetime(2026, 9, 18, 9, 0, 0, tzinfo=timezone.utc)


def _required(field):
    return (
        field.default is dataclasses.MISSING
        and field.default_factory is dataclasses.MISSING
    )


def _make_ai_response(text="pong"):
    cls = ai_contracts.AIResponse
    kwargs = {}
    for field in dataclasses.fields(cls):
        name = field.name.lower()
        ann = str(field.type).lower()

        if name in {"content", "output", "text"}:
            kwargs[field.name] = text
        elif name == "message":
            message_cls = getattr(ai_contracts, "AIMessage", None)
            if message_cls is not None and dataclasses.is_dataclass(message_cls):
                mk = {}
                for mf in dataclasses.fields(message_cls):
                    mn = mf.name.lower()
                    if mn == "role":
                        mk[mf.name] = "assistant"
                    elif mn in {"content", "text", "message"}:
                        mk[mf.name] = text
                    elif _required(mf):
                        raise AssertionError(
                            f"unsupported required AIMessage field: {mf.name}"
                        )
                kwargs[field.name] = message_cls(**mk)
            else:
                kwargs[field.name] = text
        elif name == "model":
            kwargs[field.name] = "dummy-model"
        elif name == "usage":
            usage_cls = getattr(ai_contracts, "AIUsage", None)
            if usage_cls is not None:
                kwargs[field.name] = usage_cls()
            elif _required(field):
                raise AssertionError("AIResponse requires unsupported usage")
        elif name == "tool_calls" and _required(field):
            kwargs[field.name] = ()
        elif name == "finish_reason" and _required(field):
            kwargs[field.name] = "stop"
        elif "dict" in ann or "mapping" in ann:
            if _required(field):
                kwargs[field.name] = {}
        elif "tuple" in ann or "sequence" in ann or "list" in ann:
            if _required(field):
                kwargs[field.name] = ()
        elif _required(field):
            if "bool" in ann:
                kwargs[field.name] = True
            elif "int" in ann:
                kwargs[field.name] = 0
            elif "str" in ann:
                kwargs[field.name] = ""
            else:
                raise AssertionError(
                    f"unsupported required AIResponse field: {field.name}"
                )

    return cls(**kwargs)


class FakeAIGateway:
    def __init__(self):
        self.readiness_calls = []
        self.complete_calls = []
        self.requests = []
        self.raw_response = _make_ai_response("pong")

    def readiness(self, route_id=None):
        self.readiness_calls.append(route_id)
        raise AssertionError(
            "gateway readiness must not be used by live-readiness runtime"
        )

    def complete(self, request, route_id=None, *, job_id=None):
        self.complete_calls.append(route_id)
        self.requests.append(request)
        return self.raw_response


class AF05LiveWiringTests(unittest.TestCase):
    def test_allow_live_false_blocks_before_http_or_gateway(self):
        gateway = FakeAIGateway()
        http_calls = []

        def fake_get(url, timeout):
            http_calls.append((url, timeout))
            return LiveHTTPResult(200, "ok")

        with self.assertRaisesRegex(
            LiveReadinessPermissionError,
            "explicit allow_live=True",
        ):
            build_default_zero_cost_live_wiring(
                gateway=gateway,
                route_id="route-local-qwen",
                model="dummy-model",
                allow_live=False,
                http_get=fake_get,
                clock=lambda: FIXED_TIME,
            )

        self.assertEqual(http_calls, [])
        self.assertEqual(gateway.readiness_calls, [])
        self.assertEqual(gateway.complete_calls, [])

    def test_local_qwen_live_readiness_and_run_are_integrated(self):
        gateway = FakeAIGateway()
        http_calls = []

        def fake_get(url, timeout):
            http_calls.append((url, timeout))
            return LiveHTTPResult(200, "health ok")

        wiring = build_default_zero_cost_live_wiring(
            gateway=gateway,
            route_id="route-local-qwen",
            model="dummy-model",
            allow_live=True,
            http_get=fake_get,
            clock=lambda: FIXED_TIME,
            timeout_seconds=1.25,
        )

        runtime = wiring.runtime
        self.assertEqual(runtime.name(), "gateway:local-qwen")

        readiness = runtime.readiness()
        result = runtime.run(AgentRunRequest(prompt="ping"))

        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.status, "READY")
        self.assertEqual(readiness.metadata["source"], "LIVE")
        self.assertEqual(readiness.metadata["backend_id"], "local-qwen")
        self.assertEqual(
            readiness.metadata["checked_at"],
            FIXED_TIME.isoformat(),
        )
        self.assertEqual(
            http_calls,
            [(LOCAL_QWEN.readiness_url, 1.25)],
        )

        self.assertEqual(result.status, "COMPLETED")
        self.assertEqual(result.output, "pong")
        self.assertEqual(gateway.readiness_calls, [])
        self.assertEqual(gateway.complete_calls, ["route-local-qwen"])

    def test_explicit_9router_live_wiring_never_touches_qwen(self):
        gateway = FakeAIGateway()
        http_calls = []

        def fake_get(url, timeout):
            http_calls.append((url, timeout))
            return LiveHTTPResult(200, "models ok")

        wiring = build_live_local_agent_wiring(
            gateway=gateway,
            backend_id="9router",
            route_id="route-9router",
            model="dummy-model",
            allow_live=True,
            http_get=fake_get,
            clock=lambda: FIXED_TIME,
        )

        runtime = wiring.runtime
        self.assertEqual(runtime.name(), "gateway:9router")
        runtime.readiness()
        runtime.run(AgentRunRequest(prompt="ping"))

        self.assertEqual(
            http_calls,
            [(ROUTER_9.readiness_url, 2.5)],
        )
        self.assertEqual(gateway.complete_calls, ["route-9router"])
        self.assertNotIn(LOCAL_QWEN.readiness_url, [x[0] for x in http_calls])
        self.assertNotIn("route-local-qwen", gateway.complete_calls)

    def test_unavailable_live_backend_surfaces_perlu_perhatian_without_fallback(self):
        gateway = FakeAIGateway()
        http_calls = []

        def fake_get(url, timeout):
            http_calls.append((url, timeout))
            return LiveHTTPResult(0, "connection refused")

        wiring = build_default_zero_cost_live_wiring(
            gateway=gateway,
            route_id="route-local-qwen",
            model="dummy-model",
            allow_live=True,
            http_get=fake_get,
            clock=lambda: FIXED_TIME,
        )

        readiness = wiring.runtime.readiness()

        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.status, "PERLU_PERHATIAN")
        self.assertEqual(
            http_calls,
            [(LOCAL_QWEN.readiness_url, 2.5)],
        )
        self.assertEqual(gateway.readiness_calls, [])
        self.assertEqual(gateway.complete_calls, [])

    def test_readiness_is_on_demand_not_auto_refresh(self):
        gateway = FakeAIGateway()
        http_calls = []

        def fake_get(url, timeout):
            http_calls.append(url)
            return LiveHTTPResult(200, "ok")

        wiring = build_default_zero_cost_live_wiring(
            gateway=gateway,
            route_id="route-local-qwen",
            model="dummy-model",
            allow_live=True,
            http_get=fake_get,
            clock=lambda: FIXED_TIME,
        )

        self.assertEqual(http_calls, [])
        wiring.runtime.readiness()
        self.assertEqual(len(http_calls), 1)
        wiring.runtime.readiness()
        self.assertEqual(len(http_calls), 2)

    def test_unknown_backend_blocks_before_http_or_gateway(self):
        gateway = FakeAIGateway()
        http_calls = []

        with self.assertRaisesRegex(KeyError, "unknown local backend"):
            build_live_local_agent_wiring(
                gateway=gateway,
                backend_id="unknown",
                route_id="route-unknown",
                model="dummy-model",
                allow_live=True,
                http_get=lambda url, timeout: http_calls.append(url)
                or LiveHTTPResult(200, "ok"),
                clock=lambda: FIXED_TIME,
            )

        self.assertEqual(http_calls, [])
        self.assertEqual(gateway.readiness_calls, [])
        self.assertEqual(gateway.complete_calls, [])


if __name__ == "__main__":
    unittest.main()
