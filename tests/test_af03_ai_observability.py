from __future__ import annotations

import unittest
from datetime import datetime, timezone

from xp.activity import ActivityStatus
from xp.ai.contracts import (
    AIGatewayError,
    AIReadiness,
    AIRequest,
    AIResponse,
    AITransport,
    AITransportError,
    AIUsage,
    AIRoute,
)
from xp.ai.gateway import AIGateway
from xp.ai.settings import AISettings
from xp.capabilities import (
    CapabilityRegistry,
    CapabilityState,
)


FIXED = datetime(
    2026, 9, 17, 14, 0,
    tzinfo=timezone.utc,
)


class ListRecorder:
    def __init__(self):
        self.events = []

    def record(self, event):
        self.events.append(event)


class FakeTransport(AITransport):
    def __init__(
        self,
        *,
        returned_model="actual-model",
        error=None,
    ):
        self.returned_model = returned_model
        self.error = error
        self.complete_calls = 0
        self.readiness_calls = 0

    def capability_name(self):
        return "fake-ai"

    def readiness(self, route):
        self.readiness_calls += 1
        return AIReadiness(
            ready=True,
            status="READY",
            detail="ready",
            route_id=route.route_id,
        )

    def complete(self, route, request):
        self.complete_calls += 1

        if self.error is not None:
            raise self.error

        return AIResponse(
            route_id=route.route_id,
            model=self.returned_model,
            text="observable response",
            tool_calls=(),
            usage=AIUsage(
                input_tokens=3,
                output_tokens=5,
                total_tokens=8,
            ),
            finish_reason="stop",
            served_model=self.returned_model,
        )


def settings():
    return AISettings(
        version=1,
        default_route="primary",
        routes={
            "primary": AIRoute(
                route_id="primary",
                transport="primary-transport",
                base_url="https://primary.invalid/v1",
                model="configured-model",
                secret_env="PRIMARY_KEY",
                cost_class="free",
            ),
            "fallback": AIRoute(
                route_id="fallback",
                transport="fallback-transport",
                base_url="https://fallback.invalid/v1",
                model="fallback-model",
                secret_env="FALLBACK_KEY",
                cost_class="free",
            ),
        },
    )


REQUEST = AIRequest(
    messages=(
        {
            "role": "user",
            "content": "private prompt content",
        },
    ),
)


class AIGatewayObservabilityTests(unittest.TestCase):
    def test_success_records_actual_returned_model_and_selected_route(self):
        primary = FakeTransport(
            returned_model="provider-actual-model"
        )
        fallback = FakeTransport()

        recorder = ListRecorder()
        registry = CapabilityRegistry()

        gateway = AIGateway(
            settings(),
            transports={
                "primary-transport": primary,
                "fallback-transport": fallback,
            },
            activity_recorder=recorder,
            activity_job_id="JOB-AI-001",
            capability_registry=registry,
            now=lambda: FIXED,
        )

        response = gateway.complete(
            REQUEST,
            route_id="primary",
        )

        self.assertEqual(
            response.model,
            "provider-actual-model",
        )
        self.assertEqual(primary.complete_calls, 1)
        self.assertEqual(fallback.complete_calls, 0)

        self.assertEqual(len(recorder.events), 1)
        item = recorder.events[0]

        self.assertIs(
            item.status,
            ActivityStatus.NEEDS_ATTENTION,
        )
        self.assertEqual(item.job_id, "JOB-AI-001")
        self.assertEqual(
            item.provenance.processor,
            "provider-actual-model",
        )
        self.assertEqual(
            item.provenance.via,
            "primary-transport",
        )
        self.assertFalse(item.provenance.live)

        self.assertEqual(
            item.metadata["route_id"],
            "primary",
        )
        self.assertEqual(
            item.metadata["model"],
            "provider-actual-model",
        )
        self.assertEqual(
            item.metadata["transport"],
            "primary-transport",
        )
        self.assertEqual(
            item.metadata["configured_model"],
            "configured-model",
        )
        self.assertEqual(
            item.metadata["served_model"],
            "provider-actual-model",
        )

        capability = registry.get("ai:primary")
        self.assertIs(
            capability.state,
            CapabilityState.NEEDS_ATTENTION,
        )

        rendered = repr(item)
        self.assertNotIn(
            "private prompt content",
            rendered,
        )
        self.assertNotIn("PRIMARY_KEY", rendered)

    def test_selected_route_failure_does_not_fallback(self):
        primary = FakeTransport(
            error=AITransportError(
                "primary provider failed"
            )
        )
        fallback = FakeTransport()

        recorder = ListRecorder()
        registry = CapabilityRegistry()

        gateway = AIGateway(
            settings(),
            transports={
                "primary-transport": primary,
                "fallback-transport": fallback,
            },
            activity_recorder=recorder,
            activity_job_id="JOB-AI-002",
            capability_registry=registry,
            now=lambda: FIXED,
        )

        with self.assertRaises(AITransportError):
            gateway.complete(
                REQUEST,
                route_id="primary",
            )

        self.assertEqual(primary.complete_calls, 1)
        self.assertEqual(fallback.complete_calls, 0)

        self.assertEqual(len(recorder.events), 1)
        item = recorder.events[0]

        self.assertIs(
            item.status,
            ActivityStatus.FAILED,
        )
        self.assertNotEqual(
            item.status,
            ActivityStatus.COMPLETED,
        )

        capability = registry.get("ai:primary")
        self.assertIs(
            capability.state,
            CapabilityState.NEEDS_ATTENTION,
        )

    def test_old_gateway_constructor_remains_valid(self):
        gateway = AIGateway(
            settings(),
            transports={
                "primary-transport": FakeTransport(),
                "fallback-transport": FakeTransport(),
            },
        )

        response = gateway.complete(
            REQUEST,
            route_id="primary",
        )

        self.assertEqual(
            response.route_id,
            "primary",
        )


if __name__ == "__main__":
    unittest.main()


class AgentObservabilityTests(unittest.TestCase):
    def test_agent_event_excludes_prompt_and_output(self):
        from xp.ai.agents.base import (
            AgentReadiness,
            AgentRunRequest,
            AgentRunResult,
            AgentRuntime,
            ObservedAgentRuntime,
        )

        class FakeAgent(AgentRuntime):
            @property
            def name(self):
                return "fake-agent"

            def readiness(self):
                return AgentReadiness(
                    ready=True,
                    status="READY",
                    detail="ready",
                )

            def run(self, request):
                return AgentRunResult(
                    status="COMPLETED",
                    output=(
                        "private output "
                        "chain_of_thought=SECRET"
                    ),
                    returncode=0,
                )

        recorder = ListRecorder()

        runtime = ObservedAgentRuntime(
            FakeAgent(),
            activity_recorder=recorder,
            activity_job_id="JOB-AGENT-001",
            now=lambda: FIXED,
        )

        result = runtime.run(
            AgentRunRequest(
                prompt="private prompt SECRET",
            )
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(recorder.events), 1)

        item = recorder.events[0]

        self.assertIs(
            item.status,
            ActivityStatus.COMPLETED,
        )
        self.assertEqual(
            item.provenance.processor,
            "fake-agent",
        )

        rendered = repr(item)

        self.assertNotIn(
            "private prompt SECRET",
            rendered,
        )
        self.assertNotIn(
            "private output",
            rendered,
        )
        self.assertNotIn(
            "chain_of_thought",
            rendered,
        )
