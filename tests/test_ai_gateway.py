from __future__ import annotations

import importlib
import unittest

from xp.ai.contracts import (
    AIGatewayError,
    AIReadiness,
    AIRequest,
    AIResponse,
    AITransportError,
    AIUsage,
)
from xp.ai.settings import AISettings


class FakeTransport:
    def __init__(
        self,
        name: str,
        *,
        complete_error: Exception | None = None,
    ):
        self.name = name
        self.complete_error = complete_error
        self.readiness_calls: list[str] = []
        self.complete_calls: list[tuple[str, AIRequest]] = []

    def capability_name(self) -> str:
        return self.name

    def readiness(self, route):
        self.readiness_calls.append(route.route_id)
        return AIReadiness(
            ready=True,
            status="READY",
            detail=f"{self.name} ready",
            route_id=route.route_id,
            metadata={"transport": self.name},
        )

    def complete(self, route, request):
        self.complete_calls.append((route.route_id, request))
        if self.complete_error is not None:
            raise self.complete_error
        return AIResponse(
            route_id=route.route_id,
            model=route.model,
            text=f"response from {route.route_id}",
            tool_calls=(),
            usage=AIUsage(),
            finish_reason="stop",
        )


class AIGatewayTests(unittest.TestCase):
    def _module(self):
        try:
            return importlib.import_module("xp.ai.gateway")
        except ModuleNotFoundError:
            self.fail("xp.ai.gateway must exist for AF-02 Task 4")

    @staticmethod
    def _settings() -> AISettings:
        return AISettings.from_dict(
            {
                "version": 1,
                "default_route": "free-default",
                "routes": {
                    "free-default": {
                        "transport": "free-transport",
                        "base_url": "http://127.0.0.1:20128/v1",
                        "model": "gemini/free",
                        "secret_env": "FREE_AI_KEY",
                        "cost_class": "free",
                    },
                    "paid-backup": {
                        "transport": "paid-transport",
                        "base_url": "https://example.invalid/v1",
                        "model": "example/paid",
                        "secret_env": "PAID_AI_KEY",
                        "cost_class": "paid",
                    },
                },
            }
        )

    @staticmethod
    def _request() -> AIRequest:
        return AIRequest(
            messages=(
                {"role": "user", "content": "hello"},
            )
        )

    def test_default_route_is_selected(self):
        module = self._module()
        gateway = module.AIGateway(
            self._settings(),
            transports={
                "free-transport": FakeTransport("free-transport"),
                "paid-transport": FakeTransport("paid-transport"),
            },
        )

        route = gateway.route()

        self.assertEqual(route.route_id, "free-default")
        self.assertEqual(route.cost_class, "free")

    def test_explicit_route_is_selected(self):
        module = self._module()
        gateway = module.AIGateway(
            self._settings(),
            transports={
                "free-transport": FakeTransport("free-transport"),
                "paid-transport": FakeTransport("paid-transport"),
            },
        )

        route = gateway.route("paid-backup")

        self.assertEqual(route.route_id, "paid-backup")
        self.assertEqual(route.cost_class, "paid")

    def test_unknown_route_is_gateway_error(self):
        module = self._module()
        gateway = module.AIGateway(
            self._settings(),
            transports={
                "free-transport": FakeTransport("free-transport"),
                "paid-transport": FakeTransport("paid-transport"),
            },
        )

        with self.assertRaises(AIGatewayError):
            gateway.route("missing")

    def test_unknown_transport_is_gateway_error(self):
        module = self._module()
        settings = AISettings.from_dict(
            {
                "version": 1,
                "default_route": "broken",
                "routes": {
                    "broken": {
                        "transport": "missing-transport",
                        "base_url": "https://example.invalid/v1",
                        "model": "example/model",
                        "secret_env": "BROKEN_AI_KEY",
                        "cost_class": "unknown",
                    }
                },
            }
        )
        gateway = module.AIGateway(settings, transports={})

        with self.assertRaises(AIGatewayError):
            gateway.readiness()

    def test_readiness_delegates_exactly_once_to_selected_transport(self):
        module = self._module()
        free = FakeTransport("free-transport")
        paid = FakeTransport("paid-transport")
        gateway = module.AIGateway(
            self._settings(),
            transports={
                "free-transport": free,
                "paid-transport": paid,
            },
        )

        report = gateway.readiness()

        self.assertTrue(report.ready)
        self.assertEqual(report.route_id, "free-default")
        self.assertEqual(free.readiness_calls, ["free-default"])
        self.assertEqual(paid.readiness_calls, [])

    def test_complete_delegates_exactly_once_to_selected_transport(self):
        module = self._module()
        free = FakeTransport("free-transport")
        paid = FakeTransport("paid-transport")
        gateway = module.AIGateway(
            self._settings(),
            transports={
                "free-transport": free,
                "paid-transport": paid,
            },
        )
        request = self._request()

        response = gateway.complete(request)

        self.assertEqual(response.route_id, "free-default")
        self.assertEqual(len(free.complete_calls), 1)
        self.assertEqual(free.complete_calls[0][0], "free-default")
        self.assertIs(free.complete_calls[0][1], request)
        self.assertEqual(paid.complete_calls, [])

    def test_gateway_does_not_fallback_when_default_route_fails(self):
        module = self._module()
        free = FakeTransport(
            "free-transport",
            complete_error=AITransportError("free route failed"),
        )
        paid = FakeTransport("paid-transport")
        gateway = module.AIGateway(
            self._settings(),
            transports={
                "free-transport": free,
                "paid-transport": paid,
            },
        )

        with self.assertRaisesRegex(
            AITransportError,
            "free route failed",
        ):
            gateway.complete(self._request())

        self.assertEqual(
            [route_id for route_id, _ in free.complete_calls],
            ["free-default"],
        )
        self.assertEqual(paid.complete_calls, [])

    def test_explicit_paid_route_is_used_only_when_requested(self):
        module = self._module()
        free = FakeTransport("free-transport")
        paid = FakeTransport("paid-transport")
        gateway = module.AIGateway(
            self._settings(),
            transports={
                "free-transport": free,
                "paid-transport": paid,
            },
        )

        response = gateway.complete(
            self._request(),
            route_id="paid-backup",
        )

        self.assertEqual(response.route_id, "paid-backup")
        self.assertEqual(free.complete_calls, [])
        self.assertEqual(
            [route_id for route_id, _ in paid.complete_calls],
            ["paid-backup"],
        )

    def test_default_registry_supports_openai_compatible_transport(self):
        module = self._module()
        settings = AISettings.from_dict(
            {
                "version": 1,
                "default_route": "openai-default",
                "routes": {
                    "openai-default": {
                        "transport": "openai-compatible",
                        "base_url": "http://127.0.0.1:20128/v1",
                        "model": "gemini/free",
                        "secret_env": "AF02_MISSING_TEST_KEY",
                        "cost_class": "free",
                    }
                },
            }
        )
        gateway = module.AIGateway(settings)

        report = gateway.readiness()

        self.assertFalse(report.ready)
        self.assertEqual(report.status, "NOT_READY")
        self.assertEqual(report.route_id, "openai-default")

    def test_package_exports_ai_gateway(self):
        self._module()
        import xp.ai as ai_package

        self.assertTrue(hasattr(ai_package, "AIGateway"))
        self.assertIsNotNone(ai_package.AIGateway)


if __name__ == "__main__":
    unittest.main()
