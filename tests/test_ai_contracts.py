from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from xp.ai import contracts


class AIContractsTests(unittest.TestCase):
    def _require(self, name: str):
        value = getattr(contracts, name, None)
        self.assertIsNotNone(
            value,
            f"xp.ai.contracts must define {name}",
        )
        return value

    def test_ai_error_hierarchy_exists(self):
        ai_error = self._require("AIError")
        settings_error = self._require("AISettingsError")
        transport_error = self._require("AITransportError")
        gateway_error = self._require("AIGatewayError")

        self.assertTrue(issubclass(settings_error, ai_error))
        self.assertTrue(issubclass(transport_error, ai_error))
        self.assertTrue(issubclass(gateway_error, ai_error))

    def test_airoute_is_immutable(self):
        route_cls = self._require("AIRoute")

        route = route_cls(
            route_id="local-free",
            transport="openai-compatible",
            base_url="http://127.0.0.1:20128/v1",
            model="gemini/test",
            secret_env="TEST_AI_KEY",
            cost_class="free",
        )

        with self.assertRaises(FrozenInstanceError):
            route.model = "changed"

    def test_ai_request_defaults(self):
        request_cls = self._require("AIRequest")

        request = request_cls(
            messages=(
                {"role": "user", "content": "hello"},
            )
        )

        self.assertEqual(request.tools, ())
        self.assertFalse(request.stream)

    def test_ai_usage_defaults_to_zero(self):
        usage_cls = self._require("AIUsage")

        usage = usage_cls()

        self.assertEqual(usage.input_tokens, 0)
        self.assertEqual(usage.output_tokens, 0)
        self.assertEqual(usage.total_tokens, 0)

    def test_ai_readiness_is_structured(self):
        readiness_cls = self._require("AIReadiness")

        report = readiness_cls(
            ready=True,
            status="READY",
            detail="Configured locally.",
            route_id="local-free",
        )

        self.assertTrue(report.ready)
        self.assertEqual(report.status, "READY")
        self.assertEqual(report.detail, "Configured locally.")
        self.assertEqual(report.route_id, "local-free")
        self.assertEqual(report.metadata, {})

    def test_ai_transport_is_abstract(self):
        transport_cls = self._require("AITransport")

        with self.assertRaises(TypeError):
            transport_cls()


if __name__ == "__main__":
    unittest.main()
