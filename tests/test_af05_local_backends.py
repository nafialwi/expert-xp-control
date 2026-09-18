from __future__ import annotations

import unittest

from xp.ai.agents import AgentReadiness, AgentRunRequest, AgentRunResult
from xp.ai.agents.local_backends import (
    DEFAULT_ZERO_COST_BACKEND_ID,
    LOCAL_QWEN,
    ROUTER_9,
    LocalBackendBinding,
    build_bound_runtime,
    local_backend_ids,
    resolve_local_backend,
)


class AF05LocalBackendBindingTests(unittest.TestCase):
    def _readiness(self):
        return AgentReadiness(ready=True, status="READY", detail="dummy-ready")

    def _request(self):
        return AgentRunRequest(prompt="ping")

    def _result(self):
        return AgentRunResult(status="pong", output="pong")

    def test_registry_contains_only_explicit_known_backends(self):
        self.assertEqual(local_backend_ids(), ("local-qwen", "9router"))
        self.assertIs(resolve_local_backend("local-qwen"), LOCAL_QWEN)
        self.assertIs(resolve_local_backend("9router"), ROUTER_9)

    def test_default_zero_cost_backend_is_local_qwen(self):
        self.assertEqual(DEFAULT_ZERO_COST_BACKEND_ID, "local-qwen")
        self.assertEqual(LOCAL_QWEN.policy_classification, "free-local")

    def test_9router_does_not_claim_free_cost(self):
        self.assertEqual(ROUTER_9.policy_classification, "policy-controlled")

    def test_all_builtin_backend_urls_are_loopback_only(self):
        for backend in (LOCAL_QWEN, ROUTER_9):
            self.assertTrue(backend.is_loopback)
            self.assertIn("127.0.0.1", backend.api_base_url)
            self.assertIn("127.0.0.1", backend.readiness_url)

    def test_unknown_backend_never_falls_back(self):
        with self.assertRaisesRegex(KeyError, "unknown local backend"):
            resolve_local_backend("does-not-exist")

    def test_backend_selection_must_be_explicit(self):
        for value in ("", "   ", None):
            with self.assertRaisesRegex(ValueError, "explicit"):
                resolve_local_backend(value)

    def test_non_loopback_binding_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            LocalBackendBinding(
                backend_id="bad",
                display_name="Bad",
                api_base_url="https://example.com/v1",
                readiness_url="https://example.com/health",
            )

    def test_bound_runtime_keeps_backend_identity_visible_and_delegates(self):
        readiness_calls = []
        run_calls = []
        readiness = self._readiness()
        result = self._result()
        request = self._request()

        def probe():
            readiness_calls.append("called")
            return readiness

        def handler(received):
            run_calls.append(received)
            return result

        runtime = build_bound_runtime(
            LOCAL_QWEN,
            readiness_probe=probe,
            run_handler=handler,
        )

        self.assertEqual(runtime.name(), "backend:local-qwen")
        self.assertIs(runtime.readiness(), readiness)
        self.assertIs(runtime.run(request), result)
        self.assertEqual(readiness_calls, ["called"])
        self.assertEqual(run_calls, [request])

    def test_build_bound_runtime_rejects_non_binding_object(self):
        with self.assertRaisesRegex(TypeError, "LocalBackendBinding"):
            build_bound_runtime(
                object(),
                readiness_probe=self._readiness,
                run_handler=lambda request: self._result(),
            )


if __name__ == "__main__":
    unittest.main()
