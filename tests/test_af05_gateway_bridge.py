from __future__ import annotations

import unittest

from xp.ai.agents import AgentReadiness, AgentRunRequest, AgentRunResult
from xp.ai.agents.gateway_bridge import (
    GatewayRuntimeBridge,
    build_gateway_runtime,
)
from xp.ai.agents.local_backends import LOCAL_QWEN, ROUTER_9


class FakeGateway:
    def __init__(self, readiness, result):
        self._readiness = readiness
        self._result = result
        self.readiness_calls = []
        self.complete_calls = []

    def readiness(self, backend):
        self.readiness_calls.append(backend)
        return self._readiness

    def complete(self, backend, request):
        self.complete_calls.append((backend, request))
        return self._result


class AF05GatewayBridgeTests(unittest.TestCase):
    def _readiness(self):
        return AgentReadiness(ready=True, status="READY", detail="dummy-ready")

    def _request(self):
        return AgentRunRequest(prompt="ping")

    def _result(self):
        return AgentRunResult(status="pong", output="pong")

    def test_dummy_e2e_uses_exact_backend_once_without_fallback(self):
        readiness = self._readiness()
        result = self._result()
        request = self._request()
        gateway = FakeGateway(readiness, result)

        runtime = build_gateway_runtime(
            backend=LOCAL_QWEN,
            gateway=gateway,
        )

        self.assertEqual(runtime.name(), "gateway:local-qwen")
        self.assertIs(runtime.readiness(), readiness)
        self.assertIs(runtime.run(request), result)

        self.assertEqual(gateway.readiness_calls, [LOCAL_QWEN])
        self.assertEqual(gateway.complete_calls, [(LOCAL_QWEN, request)])
        self.assertNotIn(ROUTER_9, gateway.readiness_calls)
        self.assertTrue(
            all(call[0] is not ROUTER_9 for call in gateway.complete_calls)
        )

    def test_bridge_keeps_explicit_backend_visible(self):
        gateway = FakeGateway(self._readiness(), self._result())
        bridge = GatewayRuntimeBridge(
            backend=ROUTER_9,
            gateway=gateway,
        )
        self.assertIs(bridge.backend, ROUTER_9)

    def test_bridge_rejects_non_binding_backend(self):
        gateway = FakeGateway(self._readiness(), self._result())
        with self.assertRaisesRegex(TypeError, "LocalBackendBinding"):
            GatewayRuntimeBridge(
                backend=object(),
                gateway=gateway,
            )

    def test_bridge_requires_readiness_and_complete_methods(self):
        with self.assertRaisesRegex(TypeError, "readiness"):
            GatewayRuntimeBridge(
                backend=LOCAL_QWEN,
                gateway=object(),
            )

        class ReadinessOnly:
            def readiness(self, backend):
                return self_readiness

        self_readiness = self._readiness()
        with self.assertRaisesRegex(TypeError, "complete"):
            GatewayRuntimeBridge(
                backend=LOCAL_QWEN,
                gateway=ReadinessOnly(),
            )

    def test_wrong_gateway_readiness_type_is_rejected(self):
        gateway = FakeGateway(object(), self._result())
        runtime = build_gateway_runtime(
            backend=LOCAL_QWEN,
            gateway=gateway,
        )
        with self.assertRaisesRegex(TypeError, "AgentReadiness"):
            runtime.readiness()

    def test_wrong_gateway_result_type_is_rejected(self):
        gateway = FakeGateway(self._readiness(), object())
        runtime = build_gateway_runtime(
            backend=LOCAL_QWEN,
            gateway=gateway,
        )
        with self.assertRaisesRegex(TypeError, "AgentRunResult"):
            runtime.run(self._request())


if __name__ == "__main__":
    unittest.main()
