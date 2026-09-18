from __future__ import annotations

import unittest

from xp.ai.agents.base import AgentRunRequest
from xp.ai.agents.default_wiring import LocalAgentWiring
from xp.ai.agents.live_smoke import LiveSmokeResult, run_guarded_live_smoke
from xp.ai.agents.local_backends import LOCAL_QWEN, ROUTER_9


class FakeRuntime:
    def __init__(self, readiness, result):
        self._readiness = readiness
        self._result = result
        self.readiness_calls = 0
        self.run_calls = []

    def readiness(self):
        self.readiness_calls += 1
        return self._readiness

    def run(self, request):
        self.run_calls.append(request)
        return self._result


class AF05LiveSmokeTests(unittest.TestCase):
    def _ready(self):
        from xp.ai.agents.base import AgentReadiness
        return AgentReadiness(ready=True, status="READY", detail="dummy-ready")

    def _not_ready(self):
        from xp.ai.agents.base import AgentReadiness
        return AgentReadiness(ready=False, status="PERLU_PERHATIAN", detail="connection refused")

    def _result(self):
        from xp.ai.agents.base import AgentRunResult
        return AgentRunResult(status="COMPLETED", output="pong")

    def _wiring(self, *, backend=LOCAL_QWEN, readiness=None):
        runtime = FakeRuntime(
            readiness if readiness is not None else self._ready(),
            self._result(),
        )
        wiring = LocalAgentWiring(
            backend=backend,
            route_id="route-test",
            model="dummy-model",
            runtime=runtime,
        )
        return wiring, runtime

    def test_readiness_only_is_default_and_never_runs_inference(self):
        wiring, runtime = self._wiring()

        result = run_guarded_live_smoke(wiring)

        self.assertIsInstance(result, LiveSmokeResult)
        self.assertTrue(result.ready)
        self.assertFalse(result.inference_attempted)
        self.assertIsNone(result.run_result)
        self.assertEqual(runtime.readiness_calls, 1)
        self.assertEqual(runtime.run_calls, [])

    def test_not_ready_never_runs_inference_even_when_requested(self):
        wiring, runtime = self._wiring(readiness=self._not_ready())

        result = run_guarded_live_smoke(
            wiring,
            allow_inference=True,
            smoke_prompt="ping",
        )

        self.assertFalse(result.ready)
        self.assertFalse(result.inference_attempted)
        self.assertIsNone(result.run_result)
        self.assertEqual(runtime.readiness_calls, 1)
        self.assertEqual(runtime.run_calls, [])

    def test_inference_requires_explicit_flag_and_prompt(self):
        wiring, runtime = self._wiring()

        with self.assertRaisesRegex(ValueError, "smoke_prompt must be explicit"):
            run_guarded_live_smoke(
                wiring,
                allow_inference=True,
                smoke_prompt="",
            )

        self.assertEqual(runtime.readiness_calls, 1)
        self.assertEqual(runtime.run_calls, [])

    def test_explicit_inference_runs_once_after_ready(self):
        wiring, runtime = self._wiring()

        result = run_guarded_live_smoke(
            wiring,
            allow_inference=True,
            smoke_prompt="hello",
        )

        self.assertTrue(result.ready)
        self.assertTrue(result.inference_attempted)
        self.assertIs(result.run_result, runtime._result)
        self.assertEqual(runtime.readiness_calls, 1)
        self.assertEqual(len(runtime.run_calls), 1)
        self.assertIsInstance(runtime.run_calls[0], AgentRunRequest)
        self.assertEqual(runtime.run_calls[0].prompt, "hello")

    def test_backend_identity_is_preserved_without_fallback(self):
        wiring, runtime = self._wiring(backend=ROUTER_9)

        result = run_guarded_live_smoke(wiring)

        self.assertEqual(result.backend_id, "9router")
        self.assertEqual(runtime.readiness_calls, 1)
        self.assertEqual(runtime.run_calls, [])

    def test_wrong_wiring_type_is_rejected_before_any_action(self):
        with self.assertRaisesRegex(TypeError, "LocalAgentWiring"):
            run_guarded_live_smoke(object())


if __name__ == "__main__":
    unittest.main()
