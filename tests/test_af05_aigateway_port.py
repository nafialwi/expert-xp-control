from __future__ import annotations

import unittest

from xp.ai.agents import AgentReadiness, AgentRunRequest, AgentRunResult
from xp.ai.agents.aigateway_port import AIGatewayPortAdapter
from xp.ai.agents.gateway_bridge import build_gateway_runtime
from xp.ai.agents.local_backends import LOCAL_QWEN, ROUTER_9


class FakeAIGateway:
    def __init__(self):
        self.readiness_calls = []
        self.complete_calls = []
        self.raw_readiness = object()
        self.raw_response = object()

    def readiness(self, *, route_id):
        self.readiness_calls.append(route_id)
        return self.raw_readiness

    def complete(self, *, request, route_id):
        self.complete_calls.append((route_id, request))
        return self.raw_response


class AF05AIGatewayPortTests(unittest.TestCase):
    def _readiness(self):
        return AgentReadiness(ready=True, status="READY", detail="dummy-ready")

    def _request(self):
        return AgentRunRequest(prompt="ping")

    def _result(self):
        return AgentRunResult(status="COMPLETED", output="pong")

    def _port(self, gateway=None, routes=None):
        gateway = gateway or FakeAIGateway()
        readiness = self._readiness()
        result = self._result()
        encoded = object()

        port = AIGatewayPortAdapter(
            gateway=gateway,
            route_by_backend=routes or {
                "local-qwen": "route-local-qwen",
                "9router": "route-9router",
            },
            readiness_decoder=lambda raw: readiness,
            request_encoder=lambda backend, request: encoded,
            response_decoder=lambda raw: result,
        )
        return gateway, port, readiness, result, encoded

    def test_local_qwen_uses_only_its_explicit_route(self):
        gateway, port, readiness, result, encoded = self._port()
        request = self._request()

        self.assertIs(port.readiness(LOCAL_QWEN), readiness)
        self.assertIs(port.complete(LOCAL_QWEN, request), result)

        self.assertEqual(gateway.readiness_calls, ["route-local-qwen"])
        self.assertEqual(
            gateway.complete_calls,
            [("route-local-qwen", encoded)],
        )

    def test_9router_uses_only_its_explicit_route(self):
        gateway, port, readiness, result, encoded = self._port()
        request = self._request()

        self.assertIs(port.readiness(ROUTER_9), readiness)
        self.assertIs(port.complete(ROUTER_9, request), result)

        self.assertEqual(gateway.readiness_calls, ["route-9router"])
        self.assertEqual(
            gateway.complete_calls,
            [("route-9router", encoded)],
        )

    def test_missing_route_never_falls_back_or_calls_gateway(self):
        gateway, port, _, _, _ = self._port(
            routes={"local-qwen": "route-local-qwen"}
        )

        with self.assertRaisesRegex(KeyError, "no explicit AIGateway route"):
            port.readiness(ROUTER_9)

        with self.assertRaisesRegex(KeyError, "no explicit AIGateway route"):
            port.complete(ROUTER_9, self._request())

        self.assertEqual(gateway.readiness_calls, [])
        self.assertEqual(gateway.complete_calls, [])

    def test_route_map_is_read_only(self):
        _, port, _, _, _ = self._port()
        with self.assertRaises(TypeError):
            port.route_by_backend["local-qwen"] = "changed"

    def test_decoders_must_return_agent_contract_types(self):
        gateway = FakeAIGateway()

        bad_readiness = AIGatewayPortAdapter(
            gateway=gateway,
            route_by_backend={"local-qwen": "route-local-qwen"},
            readiness_decoder=lambda raw: object(),
            request_encoder=lambda backend, request: object(),
            response_decoder=lambda raw: self._result(),
        )
        with self.assertRaisesRegex(TypeError, "AgentReadiness"):
            bad_readiness.readiness(LOCAL_QWEN)

        bad_result = AIGatewayPortAdapter(
            gateway=gateway,
            route_by_backend={"local-qwen": "route-local-qwen"},
            readiness_decoder=lambda raw: self._readiness(),
            request_encoder=lambda backend, request: object(),
            response_decoder=lambda raw: object(),
        )
        with self.assertRaisesRegex(TypeError, "AgentRunResult"):
            bad_result.complete(LOCAL_QWEN, self._request())

    def test_gateway_bridge_dummy_e2e_through_aigateway_port(self):
        gateway, port, readiness, result, encoded = self._port()
        request = self._request()

        runtime = build_gateway_runtime(
            backend=LOCAL_QWEN,
            gateway=port,
        )

        self.assertEqual(runtime.name(), "gateway:local-qwen")
        self.assertIs(runtime.readiness(), readiness)
        self.assertIs(runtime.run(request), result)

        self.assertEqual(gateway.readiness_calls, ["route-local-qwen"])
        self.assertEqual(
            gateway.complete_calls,
            [("route-local-qwen", encoded)],
        )


if __name__ == "__main__":
    unittest.main()
