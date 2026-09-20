from __future__ import annotations

import unittest

from xp_next.local_qwen import LocalQwenAdapter, LocalQwenConfigError
from xp_next.reasoning import ReasoningRequest, ReasoningStatus
from xp_next.task_contract import TaskIntent, TaskIntentKind


class LocalQwenAdapterTests(unittest.TestCase):
    def _request(self):
        return ReasoningRequest(
            task=TaskIntent.read_only(
                goal="Jelaskan stack",
                kind=TaskIntentKind.EXPLAIN,
            ),
            context={
                "network_used": False,
                "project": {"id": "p1"},
                "observed": {"markers": {"pyproject_toml": True}},
                "inferred": {"stack_hints": ["python"]},
            },
            max_tokens=64,
        )

    def test_remote_base_url_is_rejected(self):
        with self.assertRaises(LocalQwenConfigError):
            LocalQwenAdapter(base_url="https://example.com", model="local")

    def test_readiness_is_explicit_and_loopback_only(self):
        calls = []

        def request_json(method, url, payload, timeout):
            calls.append((method, url, payload))
            return {"status": "ok"}

        adapter = LocalQwenAdapter(
            base_url="http://127.0.0.1:8080",
            model="local",
            request_json=request_json,
        )
        readiness = adapter.readiness()
        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.status, "READY")
        self.assertEqual(calls[0][0], "GET")
        self.assertTrue(calls[0][1].endswith("/health"))

    def test_reason_returns_provider_neutral_completed_result(self):
        calls = []

        def request_json(method, url, payload, timeout):
            calls.append((method, url, payload))
            return {
                "model": "local",
                "choices": [
                    {"message": {"content": "Stack hint: Python."}}
                ],
            }

        adapter = LocalQwenAdapter(
            base_url="http://127.0.0.1:8080",
            model="local",
            request_json=request_json,
        )
        result = adapter.reason(self._request())

        self.assertEqual(result.status, ReasoningStatus.COMPLETED)
        self.assertEqual(result.backend_id, "local_qwen")
        self.assertEqual(result.model, "local")
        self.assertIn("Python", result.output)
        self.assertFalse(result.external_network_used)
        self.assertEqual(result.transport, "loopback_http")
        self.assertEqual(calls[0][0], "POST")
        self.assertTrue(calls[0][1].endswith("/v1/chat/completions"))
        self.assertEqual(calls[0][2]["model"], "local")
        self.assertEqual(calls[0][2]["max_tokens"], 64)

    def test_transport_failure_becomes_needs_attention_without_fallback(self):
        def request_json(method, url, payload, timeout):
            raise OSError("connection refused")

        adapter = LocalQwenAdapter(
            base_url="http://127.0.0.1:8080",
            model="local",
            request_json=request_json,
        )
        result = adapter.reason(self._request())
        self.assertEqual(result.status, ReasoningStatus.NEEDS_ATTENTION)
        self.assertEqual(result.output, "")
        self.assertEqual(result.backend_id, "local_qwen")
        self.assertFalse(result.external_network_used)
        self.assertIn("connection refused", result.detail)


if __name__ == "__main__":
    unittest.main()
