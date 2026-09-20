from __future__ import annotations

import unittest

from xp_next.task_contract import (
    TaskIntent,
    TaskIntentKind,
    TaskContractError,
)


class TaskContractTests(unittest.TestCase):
    def test_read_only_task_contract_is_explicit(self):
        task = TaskIntent.read_only(
            goal="Jelaskan struktur project ini",
            kind=TaskIntentKind.ANALYZE,
        )
        self.assertEqual(task.kind, TaskIntentKind.ANALYZE)
        self.assertEqual(task.risk, "read")
        self.assertFalse(task.mutation_allowed)
        self.assertFalse(task.network_allowed)
        self.assertEqual(task.source, "user")

    def test_empty_goal_is_rejected(self):
        with self.assertRaises(TaskContractError):
            TaskIntent.read_only(goal="   ", kind=TaskIntentKind.INSPECT)

    def test_initial_contract_has_only_read_only_intents(self):
        self.assertEqual(
            {item.value for item in TaskIntentKind},
            {"INSPECT", "ANALYZE", "EXPLAIN"},
        )


if __name__ == "__main__":
    unittest.main()
