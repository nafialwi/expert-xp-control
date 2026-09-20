from __future__ import annotations

import unittest
from unittest import mock

from xp_next.local_qwen import LocalQwenReadiness
from xp_next.reasoning import ReasoningResult, ReasoningStatus
from xp_next.service import build_read_only_plan
from xp_next.task_contract import TaskIntentKind


class PlanServiceTests(unittest.TestCase):
    def test_reasoning_failure_returns_needs_attention_without_plan_steps(self):
        fake_context = {
            "project": {"id": "p1", "name": "Fixture", "source_kind": "local"},
            "source_identity": {"kind": "local", "root": "/fixture"},
            "observed": {"markers": {}, "git": {}},
            "inferred": {"stack_hints": []},
            "capabilities": {},
            "task": {
                "goal": "Analyze",
                "kind": "ANALYZE",
                "risk": "read",
                "mutation_allowed": False,
                "network_allowed": False,
                "source": "user",
            },
            "network_used": False,
        }
        fake_reason = {
            "readiness": {
                "ready": False,
                "status": "NEEDS_ATTENTION",
                "detail": "server down",
                "backend_id": "local_qwen",
                "transport": "loopback_http",
                "external_network_used": False,
            },
            "result": None,
        }
        with mock.patch(
            "xp_next.service.build_project_context",
            return_value=fake_context,
        ), mock.patch(
            "xp_next.service._reason_from_context",
            return_value=fake_reason,
        ):
            result = build_read_only_plan(
                None,
                goal="Analyze",
                intent=TaskIntentKind.ANALYZE,
            )

        self.assertEqual(result["plan"]["status"], "NEEDS_ATTENTION")
        self.assertEqual(result["plan"]["steps"], [])
        self.assertEqual(result["verification"]["ok"], False)
        self.assertEqual(result["reasoning"]["readiness"]["ready"], False)


    def test_plan_uses_one_project_context_snapshot(self):
        fake_context = {
            "project": {"id": "p1", "name": "Fixture", "source_kind": "git"},
            "source_identity": {
                "kind": "git",
                "branch": "main",
                "head": "a" * 40,
                "dirty": False,
            },
            "observed": {"markers": {}, "git": {}},
            "inferred": {"stack_hints": ["python"]},
            "capabilities": {},
            "task": {
                "goal": "Analyze",
                "kind": "ANALYZE",
                "risk": "read",
                "mutation_allowed": False,
                "network_allowed": False,
                "source": "user",
            },
            "network_used": False,
        }
        readiness = LocalQwenReadiness(
            ready=True,
            status="READY",
            detail="ok",
        )
        reasoning = ReasoningResult(
            status=ReasoningStatus.COMPLETED,
            output="Python project.",
            backend_id="local_qwen",
            model="local",
            transport="loopback_http",
            external_network_used=False,
        )

        with mock.patch(
            "xp_next.service.build_project_context",
            return_value=fake_context,
        ) as build_context, mock.patch(
            "xp_next.service.LocalQwenAdapter"
        ) as adapter_cls:
            adapter_cls.return_value.readiness.return_value = readiness
            adapter_cls.return_value.reason.return_value = reasoning
            result = build_read_only_plan(
                None,
                goal="Analyze",
                intent=TaskIntentKind.ANALYZE,
            )

        self.assertEqual(build_context.call_count, 1)
        self.assertTrue(result["verification"]["ok"])
        self.assertEqual(result["context"]["source_identity"]["head"], "a" * 40)


if __name__ == "__main__":
    unittest.main()
