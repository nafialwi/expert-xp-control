from __future__ import annotations

import importlib
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path


class AgentRuntimeContractTests(unittest.TestCase):
    def _module(self):
        try:
            return importlib.import_module("xp.ai.agents.base")
        except ModuleNotFoundError:
            self.fail(
                "xp.ai.agents.base must exist for AF-02 Task 5"
            )

    def test_agent_readiness_is_immutable_with_empty_metadata_default(self):
        module = self._module()

        report = module.AgentReadiness(
            ready=True,
            status="READY",
            detail="Agent runtime is available.",
        )

        self.assertTrue(report.ready)
        self.assertEqual(report.status, "READY")
        self.assertEqual(report.detail, "Agent runtime is available.")
        self.assertEqual(report.metadata, {})

        with self.assertRaises(FrozenInstanceError):
            report.status = "CHANGED"

    def test_agent_run_request_defaults_cwd_to_none_and_is_immutable(self):
        module = self._module()

        request = module.AgentRunRequest(prompt="Inspect project state.")

        self.assertEqual(request.prompt, "Inspect project state.")
        self.assertIsNone(request.cwd)

        with self.assertRaises(FrozenInstanceError):
            request.prompt = "changed"

    def test_agent_run_result_defaults_returncode_to_none_and_is_immutable(self):
        module = self._module()

        result = module.AgentRunResult(
            status="OK",
            output="done",
        )

        self.assertEqual(result.status, "OK")
        self.assertEqual(result.output, "done")
        self.assertIsNone(result.returncode)

        with self.assertRaises(FrozenInstanceError):
            result.output = "changed"

    def test_agent_runtime_is_abstract(self):
        module = self._module()

        with self.assertRaises(TypeError):
            module.AgentRuntime()

    def test_fake_runtime_satisfies_contract(self):
        module = self._module()

        class FakeRuntime(module.AgentRuntime):
            def name(self) -> str:
                return "fake"

            def readiness(self):
                return module.AgentReadiness(
                    ready=True,
                    status="READY",
                    detail="Fake runtime ready.",
                    metadata={"kind": "test"},
                )

            def run(self, request):
                cwd_text = (
                    str(request.cwd)
                    if request.cwd is not None
                    else "-"
                )
                return module.AgentRunResult(
                    status="OK",
                    output=f"{request.prompt}|{cwd_text}",
                    returncode=0,
                )

        runtime = FakeRuntime()
        request = module.AgentRunRequest(
            prompt="hello",
            cwd=Path("/tmp/project"),
        )

        self.assertEqual(runtime.name(), "fake")

        readiness = runtime.readiness()
        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.status, "READY")
        self.assertEqual(readiness.metadata, {"kind": "test"})

        result = runtime.run(request)
        self.assertEqual(result.status, "OK")
        self.assertEqual(
            result.output,
            "hello|/tmp/project",
        )
        self.assertEqual(result.returncode, 0)

    def test_agents_package_exports_contract_types(self):
        self._module()
        package = importlib.import_module("xp.ai.agents")

        for name in (
            "AgentReadiness",
            "AgentRunRequest",
            "AgentRunResult",
            "AgentRuntime",
        ):
            self.assertTrue(
                hasattr(package, name),
                f"xp.ai.agents must export {name}",
            )


if __name__ == "__main__":
    unittest.main()
