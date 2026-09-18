from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .contracts import AIRoute


class PolicyDecisionKind(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


@dataclass(frozen=True)
class PolicyDecision:
    kind: PolicyDecisionKind
    route_id: str
    model: str
    cost_class: str
    reason: str


class ZeroCostPolicy:
    def evaluate(
        self,
        route: AIRoute,
        *,
        approved_unknown: bool = False,
    ) -> PolicyDecision:
        if route.cost_class == "paid":
            return PolicyDecision(
                kind=PolicyDecisionKind.BLOCK,
                route_id=route.route_id,
                model=route.model,
                cost_class=route.cost_class,
                reason=(
                    "Known paid routes are blocked "
                    "by zero-cost policy."
                ),
            )

        if (
            route.cost_class == "unknown"
            and not approved_unknown
        ):
            return PolicyDecision(
                kind=PolicyDecisionKind.REQUIRE_APPROVAL,
                route_id=route.route_id,
                model=route.model,
                cost_class=route.cost_class,
                reason=(
                    "Cost is not verified; explicit "
                    "job approval is required."
                ),
            )

        return PolicyDecision(
            kind=PolicyDecisionKind.ALLOW,
            route_id=route.route_id,
            model=route.model,
            cost_class=route.cost_class,
            reason="Route is allowed by zero-cost policy.",
        )
