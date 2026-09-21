from __future__ import annotations

import unittest

from xp_next.reasoning import (
    ReasoningRequest,
    ReasoningResult,
    ReasoningStatus,
    ReasoningContractError,
    verify_reasoning_result,
    assess_reasoning_quality,
    compact_reasoning_context,
)
from xp_next.task_contract import TaskIntent, TaskIntentKind


class ReasoningContractTests(unittest.TestCase):
    def _task(self):
        return TaskIntent.read_only(
            goal="Jelaskan project",
            kind=TaskIntentKind.EXPLAIN,
        )

    def test_request_accepts_only_read_only_local_context(self):
        request = ReasoningRequest(
            task=self._task(),
            context={"network_used": False, "project": {"id": "p1"}},
            max_tokens=96,
        )
        self.assertEqual(request.max_tokens, 96)
        self.assertEqual(request.task.risk, "read")

    def test_request_rejects_context_that_used_network(self):
        with self.assertRaises(ReasoningContractError):
            ReasoningRequest(
                task=self._task(),
                context={"network_used": True},
            )

    def test_compact_context_keeps_semantics_but_drops_runtime_noise(self):
        full = {
            "project": {"id": "p1", "name": "Fixture", "root_path": "/tmp/p", "source_kind": "git"},
            "source_identity": {"kind": "git", "branch": "main", "head": "a" * 40, "dirty": False},
            "observed": {
                "root": "/tmp/p",
                "markers": {"package_json": True, "pyproject_toml": True},
                "git": {"inside_work_tree": True, "branch": "main", "head": "a" * 40, "dirty": False},
            },
            "inferred": {"stack_hints": ["node", "python"]},
            "capabilities": {
                "python": {
                    "state": "READY",
                    "version": "Python 3.14",
                    "executable": "/very/long/path/python",
                    "evidence": "/very/long/path/python",
                    "network_used": False,
                },
                "local_qwen": {
                    "state": "AVAILABLE",
                    "version": None,
                    "executable": None,
                    "evidence": "/very/long/model/path",
                    "network_used": False,
                },
            },
            "task": {"kind": "ANALYZE", "goal": "Analyze", "risk": "read"},
            "network_used": False,
        }
        compact = compact_reasoning_context(full)
        self.assertEqual(compact["project"]["id"], "p1")
        self.assertEqual(compact["inferred"]["stack_hints"], ["node", "python"])
        self.assertEqual(compact["capabilities"]["python"], {"state": "READY", "version": "Python 3.14"})
        self.assertEqual(compact["capabilities"]["local_qwen"], {"state": "AVAILABLE", "version": None})
        self.assertNotIn("root_path", compact["project"])
        self.assertNotIn("executable", str(compact))
        self.assertFalse(compact["network_used"])

    def test_result_verifier_accepts_nonempty_local_completion(self):
        result = ReasoningResult(
            status=ReasoningStatus.COMPLETED,
            output="Project memakai Python.",
            backend_id="local_qwen",
            model="local",
            transport="loopback_http",
            external_network_used=False,
        )
        ok, detail = verify_reasoning_result(result)
        self.assertTrue(ok, detail)

    def test_result_verifier_rejects_empty_completion(self):
        result = ReasoningResult(
            status=ReasoningStatus.COMPLETED,
            output="   ",
            backend_id="local_qwen",
            model="local",
            transport="loopback_http",
            external_network_used=False,
        )
        ok, _ = verify_reasoning_result(result)
        self.assertFalse(ok)



    def test_quality_gate_accepts_short_useful_plain_text(self):
        ok, detail = assess_reasoning_quality("Stack hint: Python project.")
        self.assertTrue(ok)
        self.assertEqual(detail, "PASS")

    def test_quality_gate_rejects_repeated_token_loop(self):
        ok, detail = assess_reasoning_quality("in in in in in in in in in in in in")
        self.assertFalse(ok)
        self.assertIn("repetition", detail)

    def test_quality_gate_rejects_symbol_dominated_noise(self):
        ok, detail = assess_reasoning_quality(
            "{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{ \" \" \" :: ,, [] }} }} abc"
        )
        self.assertFalse(ok)
        self.assertIn("structured-symbol", detail)

    def test_quality_gate_rejects_observed_fragmented_qwen_shape(self):
        observed = (
            '\"projectid\"\"in \"ne,\" \" \"\"\"ne\"{'
            '\"ne\"inside\"l\"ne\" \"in\"l戒\"l\"ne\"l'
            '\"ne\" \"l\"ne\" \"in\"l\"'
        )
        ok, detail = assess_reasoning_quality(observed)
        self.assertFalse(ok)
        self.assertIn("structured-symbol", detail)

    def test_verifier_rejects_completed_but_pathological_output(self):
        result = ReasoningResult(
            status=ReasoningStatus.COMPLETED,
            output="token token token token token token token token token token",
            backend_id="local_qwen",
            model="local",
            transport="loopback_http",
            external_network_used=False,
        )
        ok, detail = verify_reasoning_result(result)
        self.assertFalse(ok)
        self.assertIn("repetition", detail)

if __name__ == "__main__":
    unittest.main()
