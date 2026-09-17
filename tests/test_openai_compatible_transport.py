from __future__ import annotations

import importlib
import unittest

from xp.ai.contracts import (
    AIRequest,
    AITransportError,
    AIRoute,
)


class OpenAICompatibleTransportTests(unittest.TestCase):
    def _module(self):
        try:
            return importlib.import_module(
                "xp.ai.transports.openai_compatible"
            )
        except ModuleNotFoundError:
            self.fail(
                "xp.ai.transports.openai_compatible must exist for AF-02 Task 3"
            )

    @staticmethod
    def _route() -> AIRoute:
        return AIRoute(
            route_id="9router-gemini",
            transport="openai-compatible",
            base_url="http://127.0.0.1:20128/v1",
            model="gemini/gemini-3.5-flash-lite",
            secret_env="NINEROUTER_KEY",
            cost_class="free",
        )

    @staticmethod
    def _request(*, stream: bool = False) -> AIRequest:
        return AIRequest(
            messages=(
                {"role": "user", "content": "check calc"},
            ),
            tools=(
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read a file",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                            },
                            "required": ["path"],
                        },
                    },
                },
            ),
            stream=stream,
        )

    def test_capability_name_is_openai_compatible(self):
        module = self._module()
        transport = module.OpenAICompatibleTransport(
            secret_resolver=lambda name: "secret"
        )
        self.assertEqual(
            transport.capability_name(),
            "openai-compatible",
        )

    def test_readiness_missing_secret_is_not_ready_without_http(self):
        module = self._module()
        http_calls = []

        def http_post(*args, **kwargs):
            http_calls.append((args, kwargs))
            raise AssertionError("readiness must not call HTTP")

        transport = module.OpenAICompatibleTransport(
            secret_resolver=lambda name: None,
            http_post=http_post,
        )
        report = transport.readiness(self._route())

        self.assertFalse(report.ready)
        self.assertEqual(report.status, "NOT_READY")
        self.assertEqual(report.route_id, "9router-gemini")
        self.assertEqual(http_calls, [])

    def test_readiness_present_secret_is_ready_without_leaking_secret(self):
        module = self._module()
        secret = "unit-test-secret-do-not-render"
        transport = module.OpenAICompatibleTransport(
            secret_resolver=lambda name: secret
        )

        report = transport.readiness(self._route())

        self.assertTrue(report.ready)
        self.assertEqual(report.status, "READY")
        self.assertNotIn(secret, repr(report))
        self.assertNotIn(secret, report.detail)

    def test_streaming_is_explicitly_rejected(self):
        module = self._module()
        transport = module.OpenAICompatibleTransport(
            secret_resolver=lambda name: "secret"
        )

        with self.assertRaisesRegex(
            AITransportError,
            "streaming is not supported",
        ):
            transport.complete(
                self._route(),
                self._request(stream=True),
            )

    def test_complete_builds_expected_request_and_normalizes_response(self):
        module = self._module()
        captured = {}

        def http_post(url, headers, payload, timeout):
            captured["url"] = url
            captured["headers"] = dict(headers)
            captured["payload"] = payload
            captured["timeout"] = timeout
            return {
                "model": "gemini/gemini-3.5-flash-lite",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": "checking",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": "{\"path\":\"calc.mjs\"}",
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                },
            }

        transport = module.OpenAICompatibleTransport(
            secret_resolver=lambda name: "secret-value",
            http_post=http_post,
            timeout=45,
        )

        response = transport.complete(
            self._route(),
            self._request(),
        )

        self.assertEqual(
            captured["url"],
            "http://127.0.0.1:20128/v1/chat/completions",
        )
        self.assertEqual(
            captured["headers"]["Authorization"],
            "Bearer secret-value",
        )
        self.assertEqual(
            captured["headers"]["Content-Type"],
            "application/json",
        )
        self.assertEqual(
            captured["payload"]["model"],
            "gemini/gemini-3.5-flash-lite",
        )
        self.assertEqual(
            captured["payload"]["messages"],
            [{"role": "user", "content": "check calc"}],
        )
        self.assertEqual(captured["payload"]["stream"], False)
        self.assertIn("tools", captured["payload"])
        self.assertEqual(captured["timeout"], 45)

        self.assertEqual(response.route_id, "9router-gemini")
        self.assertEqual(
            response.model,
            "gemini/gemini-3.5-flash-lite",
        )
        self.assertEqual(response.text, "checking")
        self.assertEqual(response.finish_reason, "tool_calls")
        self.assertEqual(len(response.tool_calls), 1)
        self.assertEqual(response.tool_calls[0].call_id, "call_1")
        self.assertEqual(response.tool_calls[0].name, "read_file")
        self.assertEqual(
            response.tool_calls[0].arguments,
            {"path": "calc.mjs"},
        )
        self.assertEqual(response.usage.input_tokens, 100)
        self.assertEqual(response.usage.output_tokens, 20)
        self.assertEqual(response.usage.total_tokens, 120)

    def test_missing_usage_and_model_are_normalized(self):
        module = self._module()

        def http_post(url, headers, payload, timeout):
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": None,
                        },
                    }
                ]
            }

        transport = module.OpenAICompatibleTransport(
            secret_resolver=lambda name: "secret",
            http_post=http_post,
        )
        response = transport.complete(
            self._route(),
            AIRequest(
                messages=(
                    {"role": "user", "content": "hello"},
                )
            ),
        )

        self.assertEqual(response.model, self._route().model)
        self.assertEqual(response.text, "")
        self.assertEqual(response.tool_calls, ())
        self.assertEqual(response.usage.input_tokens, 0)
        self.assertEqual(response.usage.output_tokens, 0)
        self.assertEqual(response.usage.total_tokens, 0)

    def test_tools_are_omitted_when_request_has_none(self):
        module = self._module()
        captured = {}

        def http_post(url, headers, payload, timeout):
            captured["payload"] = payload
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "ok"},
                    }
                ]
            }

        transport = module.OpenAICompatibleTransport(
            secret_resolver=lambda name: "secret",
            http_post=http_post,
        )
        transport.complete(
            self._route(),
            AIRequest(
                messages=(
                    {"role": "user", "content": "hello"},
                )
            ),
        )

        self.assertNotIn("tools", captured["payload"])

    def test_missing_secret_blocks_complete(self):
        module = self._module()
        transport = module.OpenAICompatibleTransport(
            secret_resolver=lambda name: None
        )

        with self.assertRaises(AITransportError):
            transport.complete(
                self._route(),
                self._request(),
            )

    def test_http_failure_is_normalized_and_secret_is_not_exposed(self):
        module = self._module()
        secret = "very-private-unit-test-secret"

        def http_post(url, headers, payload, timeout):
            raise RuntimeError(
                "provider exploded with " + secret
            )

        transport = module.OpenAICompatibleTransport(
            secret_resolver=lambda name: secret,
            http_post=http_post,
        )

        with self.assertRaises(AITransportError) as ctx:
            transport.complete(
                self._route(),
                self._request(),
            )

        self.assertNotIn(secret, str(ctx.exception))
        self.assertIn(
            "OpenAI-compatible request failed",
            str(ctx.exception),
        )

    def test_malformed_tool_arguments_are_rejected(self):
        module = self._module()

        def http_post(url, headers, payload, timeout):
            return {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_bad",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": "not-json",
                                    },
                                }
                            ],
                        },
                    }
                ]
            }

        transport = module.OpenAICompatibleTransport(
            secret_resolver=lambda name: "secret",
            http_post=http_post,
        )

        with self.assertRaises(AITransportError):
            transport.complete(
                self._route(),
                self._request(),
            )

    def test_tool_arguments_must_decode_to_object(self):
        module = self._module()

        def http_post(url, headers, payload, timeout):
            return {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_bad",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": "[]",
                                    },
                                }
                            ],
                        },
                    }
                ]
            }

        transport = module.OpenAICompatibleTransport(
            secret_resolver=lambda name: "secret",
            http_post=http_post,
        )

        with self.assertRaises(AITransportError):
            transport.complete(
                self._route(),
                self._request(),
            )


if __name__ == "__main__":
    unittest.main()
