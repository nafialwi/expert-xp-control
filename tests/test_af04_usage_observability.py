from __future__ import annotations

import importlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from xp.activity import ActivityStatus
from xp.ai.contracts import AIRequest, AIResponse, AIUsage
from xp.ai.gateway import AIGateway
from xp.ai.job_state import JobAIStateStore
from xp.ai.settings import AISettings
from xp.capabilities import CapabilityRegistry, CapabilityState


FIXED = datetime(
    2026, 9, 18, 3, 15,
    tzinfo=timezone.utc,
)

REQUEST = AIRequest(
    messages=(
        {"role": "user", "content": "private task"},
    )
)


class SequenceClock:
    def __init__(self, *values):
        self._values = iter(values)

    def __call__(self):
        return next(self._values)


class ListRecorder:
    def __init__(self):
        self.events = []

    def record(self, event):
        self.events.append(event)


class FakeTransport:
    def __init__(
        self,
        *,
        served_model,
        usage=None,
    ):
        self.served_model = served_model
        self.usage = (
            usage
            if usage is not None
            else AIUsage(
                input_tokens=7,
                output_tokens=5,
                total_tokens=12,
            )
        )
        self.complete_calls = 0

    def capability_name(self):
        return "fake"

    def readiness(self, route):
        raise AssertionError(
            "readiness must not be called by complete()"
        )

    def complete(self, route, request):
        self.complete_calls += 1
        return AIResponse(
            route_id=route.route_id,
            model=self.served_model or route.model,
            text="observable response",
            tool_calls=(),
            usage=self.usage,
            finish_reason="stop",
            served_model=self.served_model,
        )


def settings() -> AISettings:
    return AISettings.from_dict(
        {
            "version": 1,
            "default_route": "primary",
            "routes": {
                "primary": {
                    "transport": "fake",
                    "base_url": "https://example.invalid/v1",
                    "model": "configured-model",
                    "secret_env": "FAKE_KEY",
                    "cost_class": "free",
                }
            },
        }
    )


class AF04UsageObservabilityTests(unittest.TestCase):
    def _usage_module(self):
        try:
            return importlib.import_module(
                "xp.ai.usage_history"
            )
        except ModuleNotFoundError as exc:
            if exc.name == "xp.ai.usage_history":
                self.fail(
                    "xp.ai.usage_history must exist for AF-04 Task 5"
                )
            raise

    def test_missing_usage_defaults_to_unavailable_not_zero(self):
        usage = AIUsage()

        self.assertIsNone(usage.input_tokens)
        self.assertIsNone(usage.output_tokens)
        self.assertIsNone(usage.total_tokens)

    def test_reported_zero_tokens_remain_zero(self):
        transport_module = importlib.import_module(
            "xp.ai.transports.openai_compatible"
        )

        usage = transport_module.OpenAICompatibleTransport._normalize_usage(
            {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
        )

        self.assertEqual(usage.input_tokens, 0)
        self.assertEqual(usage.output_tokens, 0)
        self.assertEqual(usage.total_tokens, 0)

    def test_usage_history_records_latency_configured_and_served_model(self):
        usage_module = self._usage_module()

        with tempfile.TemporaryDirectory() as td:
            history = usage_module.UsageHistoryStore.for_home(
                Path(td)
            )
            transport = FakeTransport(
                served_model="configured-model"
            )
            gateway = AIGateway(
                settings(),
                transports={"fake": transport},
                usage_history_store=history,
                monotonic=SequenceClock(10.0, 10.125),
                now=lambda: FIXED,
            )

            gateway.complete(
                REQUEST,
                job_id="job-1",
            )

            records = history.list()

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.job_id, "job-1")
        self.assertEqual(record.route_id, "primary")
        self.assertEqual(record.transport, "fake")
        self.assertEqual(
            record.configured_model,
            "configured-model",
        )
        self.assertEqual(
            record.served_model,
            "configured-model",
        )
        self.assertEqual(record.latency_ms, 125.0)
        self.assertEqual(record.input_tokens, 7)
        self.assertEqual(record.output_tokens, 5)
        self.assertEqual(record.total_tokens, 12)
        self.assertEqual(
            record.technical_result,
            "completed",
        )

    def test_missing_tokens_remain_unavailable_in_usage_history(self):
        usage_module = self._usage_module()

        with tempfile.TemporaryDirectory() as td:
            history = usage_module.UsageHistoryStore.for_home(
                Path(td)
            )
            transport = FakeTransport(
                served_model="configured-model",
                usage=AIUsage(),
            )
            gateway = AIGateway(
                settings(),
                transports={"fake": transport},
                usage_history_store=history,
                monotonic=SequenceClock(1.0, 1.010),
                now=lambda: FIXED,
            )

            gateway.complete(
                REQUEST,
                job_id="job-usage-none",
            )

            record = history.list()[0]

        self.assertIsNone(record.input_tokens)
        self.assertIsNone(record.output_tokens)
        self.assertIsNone(record.total_tokens)

    def test_model_mismatch_returns_response_but_marks_needs_attention(self):
        usage_module = self._usage_module()

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            history = usage_module.UsageHistoryStore.for_home(
                home
            )
            job_store = JobAIStateStore.for_home(home)
            registry = CapabilityRegistry()
            recorder = ListRecorder()
            transport = FakeTransport(
                served_model="provider-other-model"
            )

            gateway = AIGateway(
                settings(),
                transports={"fake": transport},
                usage_history_store=history,
                job_state_store=job_store,
                capability_registry=registry,
                activity_recorder=recorder,
                activity_job_id="job-mismatch",
                monotonic=SequenceClock(3.0, 3.250),
                now=lambda: FIXED,
            )

            response = gateway.complete(
                REQUEST,
                job_id="job-mismatch",
            )

            state = job_store.get("job-mismatch")
            record = history.list()[0]

        self.assertEqual(
            response.model,
            "provider-other-model",
        )
        self.assertEqual(
            response.served_model,
            "provider-other-model",
        )
        self.assertIsNotNone(
            state.pending_model_mismatch
        )
        self.assertEqual(
            state.pending_model_mismatch.configured_model,
            "configured-model",
        )
        self.assertEqual(
            state.pending_model_mismatch.served_model,
            "provider-other-model",
        )

        self.assertEqual(len(recorder.events), 1)
        event = recorder.events[0]
        self.assertIs(
            event.status,
            ActivityStatus.NEEDS_ATTENTION,
        )
        self.assertEqual(
            event.metadata["configured_model"],
            "configured-model",
        )
        self.assertEqual(
            event.metadata["served_model"],
            "provider-other-model",
        )
        self.assertEqual(event.metadata["latency_ms"], 250.0)

        capability = registry.get("ai:primary")
        self.assertIs(
            capability.state,
            CapabilityState.NEEDS_ATTENTION,
        )

        self.assertEqual(
            record.technical_result,
            "needs_attention",
        )
        self.assertEqual(
            record.configured_model,
            "configured-model",
        )
        self.assertEqual(
            record.served_model,
            "provider-other-model",
        )

    def test_pending_model_mismatch_blocks_future_transport_until_acknowledged(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            job_store = JobAIStateStore.for_home(home)
            transport = FakeTransport(
                served_model="provider-other-model"
            )

            gateway = AIGateway(
                settings(),
                transports={"fake": transport},
                job_state_store=job_store,
                monotonic=SequenceClock(
                    1.0,
                    1.1,
                    2.0,
                    2.1,
                ),
                now=lambda: FIXED,
            )

            first = gateway.complete(
                REQUEST,
                job_id="job-mismatch",
            )
            self.assertEqual(
                first.served_model,
                "provider-other-model",
            )
            self.assertEqual(transport.complete_calls, 1)

            with self.assertRaisesRegex(
                Exception,
                "acknowledge",
            ) as ctx:
                gateway.complete(
                    REQUEST,
                    job_id="job-mismatch",
                )

            self.assertEqual(
                type(ctx.exception).__name__,
                "AIModelMismatchPendingError",
            )
            self.assertEqual(transport.complete_calls, 1)

            cleared = job_store.acknowledge_model_mismatch(
                "job-mismatch"
            )
            self.assertIsNone(
                cleared.pending_model_mismatch
            )

            second = gateway.complete(
                REQUEST,
                job_id="job-mismatch",
            )

            self.assertEqual(
                second.served_model,
                "provider-other-model",
            )
            self.assertEqual(transport.complete_calls, 2)

    def test_matching_served_model_is_completed(self):
        recorder = ListRecorder()
        registry = CapabilityRegistry()
        transport = FakeTransport(
            served_model="configured-model"
        )

        gateway = AIGateway(
            settings(),
            transports={"fake": transport},
            capability_registry=registry,
            activity_recorder=recorder,
            activity_job_id="job-match",
            monotonic=SequenceClock(4.0, 4.050),
            now=lambda: FIXED,
        )

        response = gateway.complete(
            REQUEST,
            job_id="job-match",
        )

        self.assertEqual(
            response.served_model,
            "configured-model",
        )
        self.assertIs(
            recorder.events[0].status,
            ActivityStatus.COMPLETED,
        )
        self.assertEqual(
            registry.get("ai:primary").state,
            CapabilityState.NOT_CHECKED,
        )

    def test_usage_store_is_local_only(self):
        usage_module = self._usage_module()

        with tempfile.TemporaryDirectory() as td:
            store = usage_module.UsageHistoryStore.for_home(
                Path(td)
            )
            record = usage_module.AIUsageObservation(
                record_id="record-1",
                timestamp=FIXED,
                job_id="job-1",
                route_id="primary",
                transport="fake",
                configured_model="configured-model",
                served_model=None,
                cost_class="free",
                latency_ms=12.0,
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
                technical_result="completed",
                error_type=None,
            )

            with patch(
                "urllib.request.urlopen",
                side_effect=AssertionError(
                    "usage history must not access network"
                ),
            ):
                store.record(record)
                loaded = store.list()

        self.assertEqual(loaded, (record,))


if __name__ == "__main__":
    unittest.main()
