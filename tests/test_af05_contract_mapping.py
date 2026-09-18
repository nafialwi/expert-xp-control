from __future__ import annotations

import dataclasses
import unittest

from xp.ai import contracts as ai_contracts
from xp.ai.agents import AgentReadiness, AgentRunRequest, AgentRunResult
from xp.ai.agents.contract_mapping import (
    AgentAIContractMappingError,
    decode_ai_readiness,
    decode_ai_response,
    encode_agent_request,
)


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


class AF05ContractMappingTests(unittest.TestCase):
    def test_encode_agent_request_maps_prompt_and_model(self):
        agent_request = AgentRunRequest(prompt="ping")
        ai_request = encode_agent_request(
            agent_request,
            model="dummy-model",
        )

        self.assertIsInstance(ai_request, ai_contracts.AIRequest)

        field_names = {f.name for f in dataclasses.fields(ai_contracts.AIRequest)}
        if "model" in field_names:
            self.assertEqual(ai_request.model, "dummy-model")

        if "prompt" in field_names:
            self.assertEqual(ai_request.prompt, "ping")
        elif "messages" in field_names:
            self.assertTrue(ai_request.messages)
            message = ai_request.messages[0]
            if isinstance(message, dict):
                self.assertEqual(message["content"], "ping")
            else:
                self.assertEqual(message.content, "ping")
        elif "input" in field_names:
            self.assertEqual(ai_request.input, "ping")
        elif "text" in field_names:
            self.assertEqual(ai_request.text, "ping")
        elif "query" in field_names:
            self.assertEqual(ai_request.query, "ping")
        else:
            self.fail("no supported prompt field in AIRequest")

    def test_encode_agent_request_requires_explicit_model_when_contract_has_model(self):
        field_names = {f.name for f in dataclasses.fields(ai_contracts.AIRequest)}
        if "model" not in field_names:
            self.skipTest("AIRequest does not expose a model field")

        with self.assertRaisesRegex(
            AgentAIContractMappingError,
            "explicit model",
        ):
            encode_agent_request(
                AgentRunRequest(prompt="ping"),
                model=None,
            )

    def test_decode_ai_response_maps_text_to_agent_result(self):
        response = _make_ai_response("pong")
        result = decode_ai_response(response)

        self.assertIsInstance(result, AgentRunResult)
        self.assertEqual(result.status, "COMPLETED")
        self.assertEqual(result.output, "pong")
        self.assertEqual(result.returncode, 0)

    def test_decode_ai_readiness_maps_ready_status_detail_and_metadata(self):
        raw = _make_ai_readiness(True)
        result = decode_ai_readiness(raw)

        self.assertIsInstance(result, AgentReadiness)
        self.assertTrue(result.ready)
        self.assertEqual(result.status.upper(), "READY")

    def test_wrong_contract_types_are_rejected(self):
        with self.assertRaisesRegex(TypeError, "AgentRunRequest"):
            encode_agent_request(object(), model="dummy-model")

        with self.assertRaisesRegex(TypeError, "AIResponse"):
            decode_ai_response(object())

        with self.assertRaisesRegex(TypeError, "AIReadiness"):
            decode_ai_readiness(object())


if __name__ == "__main__":
    unittest.main()
