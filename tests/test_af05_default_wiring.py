from __future__ import annotations

import dataclasses
import unittest

from xp.ai import contracts as ai_contracts
from xp.ai.agents import AgentRunRequest
from xp.ai.agents.default_wiring import (
    LocalAgentWiring,
    build_default_zero_cost_wiring,
    build_local_agent_wiring,
)


def _required(field):
    return (
        field.default is dataclasses.MISSING
        and field.default_factory is dataclasses.MISSING
    )


def _make_ai_readiness(ready=True):
    cls = ai_contracts.AIReadiness
    kwargs = {}
    for field in dataclasses.fields(cls):
        name = field.name.lower()
        ann = str(field.type).lower()

        if name == "ready":
            kwargs[field.name] = ready
        elif name == "status":
            kwargs[field.name] = "READY" if ready else "NOT_READY"
        elif name in {"detail", "reason", "message"}:
            kwargs[field.name] = "dummy-ready" if ready else "dummy-not-ready"
        elif name == "metadata":
            kwargs[field.name] = {"source": "dummy"}
        elif _required(field):
            if "bool" in ann:
                kwargs[field.name] = ready
            elif "dict" in ann or "mapping" in ann:
                kwargs[field.name] = {}
            elif "int" in ann:
                kwargs[field.name] = 0
            elif "str" in ann:
                kwargs[field.name] = ""
            else:
                raise AssertionError(
                    f"unsupported required AIReadiness field: {field.name}"
                )
    return cls(**kwargs)


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
        self.raw_readiness = _make_ai_readiness(True)
        self.raw_response = _make_ai_response("pong")

    def readiness(self, route_id=None):
        self.readiness_calls.append(route_id)
        return self.raw_readiness

    def complete(self, request, route_id=None, *, job_id=None):
        self.complete_calls.append(route_id)
        self.requests.append(request)
        return self.raw_response


class AF05DefaultWiringTests(unittest.TestCase):
    def test_default_zero_cost_wiring_is_local_qwen_end_to_end(self):
        gateway = FakeAIGateway()
        wiring = build_default_zero_cost_wiring(
            gateway=gateway,
            route_id="route-local-qwen",
            model="dummy-model",
        )

        self.assertIsInstance(wiring, LocalAgentWiring)
        self.assertEqual(wiring.backend.backend_id, "local-qwen")
        self.assertEqual(wiring.route_id, "route-local-qwen")
        self.assertEqual(wiring.model, "dummy-model")

        runtime = wiring.runtime
        self.assertEqual(runtime.name(), "gateway:local-qwen")
        readiness = runtime.readiness()
        result = runtime.run(AgentRunRequest(prompt="ping"))

        self.assertTrue(readiness.ready)
        self.assertEqual(result.status, "COMPLETED")
        self.assertEqual(result.output, "pong")
        self.assertEqual(gateway.readiness_calls, ["route-local-qwen"])
        self.assertEqual(gateway.complete_calls, ["route-local-qwen"])

    def test_explicit_9router_wiring_only_uses_9router_route(self):
        gateway = FakeAIGateway()
        wiring = build_local_agent_wiring(
            gateway=gateway,
            backend_id="9router",
            route_id="route-9router",
            model="dummy-model",
        )

        runtime = wiring.runtime
        self.assertEqual(runtime.name(), "gateway:9router")
        runtime.readiness()
        runtime.run(AgentRunRequest(prompt="ping"))

        self.assertEqual(gateway.readiness_calls, ["route-9router"])
        self.assertEqual(gateway.complete_calls, ["route-9router"])
        self.assertNotIn("route-local-qwen", gateway.readiness_calls)
        self.assertNotIn("route-local-qwen", gateway.complete_calls)

    def test_unknown_backend_never_calls_gateway_or_falls_back(self):
        gateway = FakeAIGateway()

        with self.assertRaisesRegex(KeyError, "unknown local backend"):
            build_local_agent_wiring(
                gateway=gateway,
                backend_id="unknown",
                route_id="route-unknown",
                model="dummy-model",
            )

        self.assertEqual(gateway.readiness_calls, [])
        self.assertEqual(gateway.complete_calls, [])

    def test_route_and_model_must_be_explicit(self):
        gateway = FakeAIGateway()

        for route in ("", "   ", None):
            with self.assertRaisesRegex(ValueError, "route_id"):
                build_local_agent_wiring(
                    gateway=gateway,
                    backend_id="local-qwen",
                    route_id=route,
                    model="dummy-model",
                )

        for model in ("", "   ", None):
            with self.assertRaisesRegex(ValueError, "model"):
                build_local_agent_wiring(
                    gateway=gateway,
                    backend_id="local-qwen",
                    route_id="route-local-qwen",
                    model=model,
                )

    def test_agent_prompt_reaches_ai_request_without_live_transport(self):
        gateway = FakeAIGateway()
        wiring = build_default_zero_cost_wiring(
            gateway=gateway,
            route_id="route-local-qwen",
            model="dummy-model",
        )

        wiring.runtime.run(AgentRunRequest(prompt="hello-xp"))
        self.assertEqual(len(gateway.requests), 1)
        request = gateway.requests[0]
        fields = {f.name for f in dataclasses.fields(ai_contracts.AIRequest)}

        if "prompt" in fields:
            self.assertEqual(request.prompt, "hello-xp")
        elif "messages" in fields:
            self.assertTrue(request.messages)
            message = request.messages[0]
            content = (
                message["content"]
                if isinstance(message, dict)
                else message.content
            )
            self.assertEqual(content, "hello-xp")
        elif "input" in fields:
            self.assertEqual(request.input, "hello-xp")
        elif "text" in fields:
            self.assertEqual(request.text, "hello-xp")
        elif "query" in fields:
            self.assertEqual(request.query, "hello-xp")
        else:
            self.fail("AIRequest has no supported prompt field")

        if "model" in fields:
            self.assertEqual(request.model, "dummy-model")


if __name__ == "__main__":
    unittest.main()
