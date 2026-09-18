from __future__ import annotations

import importlib
import unittest

from xp.ai.contracts import AIRoute


def make_route(cost_class: str) -> AIRoute:
    return AIRoute(
        route_id="r1",
        transport="openai-compatible",
        base_url="https://example.invalid/v1",
        model="example/model",
        secret_env="EXAMPLE_KEY",
        cost_class=cost_class,
    )


class AF04PolicyTests(unittest.TestCase):
    def _policy_module(self):
        try:
            return importlib.import_module("xp.ai.policy")
        except ModuleNotFoundError as exc:
            if exc.name == "xp.ai.policy":
                self.fail("xp.ai.policy must exist for AF-04 Task 1")
            raise

    def test_free_route_is_allowed(self):
        module = self._policy_module()

        decision = module.ZeroCostPolicy().evaluate(
            make_route("free")
        )

        self.assertEqual(
            decision.kind,
            module.PolicyDecisionKind.ALLOW,
        )
        self.assertEqual(decision.route_id, "r1")
        self.assertEqual(decision.model, "example/model")
        self.assertEqual(decision.cost_class, "free")

    def test_paid_route_is_hard_blocked_even_if_approval_is_claimed(self):
        module = self._policy_module()

        decision = module.ZeroCostPolicy().evaluate(
            make_route("paid"),
            approved_unknown=True,
        )

        self.assertEqual(
            decision.kind,
            module.PolicyDecisionKind.BLOCK,
        )

    def test_unknown_route_requires_approval(self):
        module = self._policy_module()

        decision = module.ZeroCostPolicy().evaluate(
            make_route("unknown")
        )

        self.assertEqual(
            decision.kind,
            module.PolicyDecisionKind.REQUIRE_APPROVAL,
        )

    def test_unknown_route_is_allowed_only_with_explicit_approval(self):
        module = self._policy_module()

        decision = module.ZeroCostPolicy().evaluate(
            make_route("unknown"),
            approved_unknown=True,
        )

        self.assertEqual(
            decision.kind,
            module.PolicyDecisionKind.ALLOW,
        )


if __name__ == "__main__":
    unittest.main()
