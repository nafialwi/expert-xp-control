from __future__ import annotations

import unittest

from xp.ai.agents import (
    AgentReadiness,
    AgentRunRequest,
    AgentRunResult,
    AgentRuntime,
    AgentRuntimeAdapter,
)


class AF05RuntimeAdapterTests(unittest.TestCase):
    def _readiness(self):
        return AgentReadiness(ready=True, status="dummy-ready", detail="dummy-ready")

    def _request(self):
        return AgentRunRequest(prompt="ping")

    def _result(self):
        return AgentRunResult(status="pong", output="pong")

    def _adapter(self, **overrides):
        values = dict(
            name="dummy-runtime",
            readiness_probe=self._readiness,
            run_handler=lambda request: self._result(),
        )
        values.update(overrides)
        return AgentRuntimeAdapter(**values)

    def test_adapter_satisfies_agent_runtime_contract(self):
        adapter = self._adapter()
        self.assertIsInstance(adapter, AgentRuntime)
        self.assertEqual(adapter.name(), "dummy-runtime")

    def test_dummy_e2e_delegates_readiness_and_run_exactly_once(self):
        readiness_calls = []
        run_calls = []
        expected_readiness = self._readiness()
        expected_result = self._result()
        request = self._request()

        def readiness_probe():
            readiness_calls.append("called")
            return expected_readiness

        def run_handler(received):
            run_calls.append(received)
            return expected_result

        adapter = self._adapter(
            readiness_probe=readiness_probe,
            run_handler=run_handler,
        )

        actual_readiness = adapter.readiness()
        actual_result = adapter.run(request)

        self.assertIs(actual_readiness, expected_readiness)
        self.assertIs(actual_result, expected_result)
        self.assertEqual(readiness_calls, ["called"])
        self.assertEqual(run_calls, [request])

    def test_adapter_rejects_non_contract_request_before_handler(self):
        calls = []
        adapter = self._adapter(
            run_handler=lambda request: calls.append(request) or self._result(),
        )

        with self.assertRaisesRegex(TypeError, "AgentRunRequest"):
            adapter.run(object())

        self.assertEqual(calls, [])

    def test_adapter_rejects_wrong_readiness_result_type(self):
        adapter = self._adapter(readiness_probe=lambda: object())
        with self.assertRaisesRegex(TypeError, "AgentReadiness"):
            adapter.readiness()

    def test_adapter_rejects_wrong_run_result_type(self):
        adapter = self._adapter(run_handler=lambda request: object())
        with self.assertRaisesRegex(TypeError, "AgentRunResult"):
            adapter.run(self._request())

    def test_constructor_validates_name_and_callable_boundaries(self):
        with self.assertRaisesRegex(ValueError, "name"):
            AgentRuntimeAdapter(
                name="   ",
                readiness_probe=self._readiness,
                run_handler=lambda request: self._result(),
            )

        with self.assertRaisesRegex(TypeError, "readiness_probe"):
            AgentRuntimeAdapter(
                name="dummy-runtime",
                readiness_probe=None,
                run_handler=lambda request: self._result(),
            )

        with self.assertRaisesRegex(TypeError, "run_handler"):
            AgentRuntimeAdapter(
                name="dummy-runtime",
                readiness_probe=self._readiness,
                run_handler=None,
            )


if __name__ == "__main__":
    unittest.main()
