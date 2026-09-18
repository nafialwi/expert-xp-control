from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path


class AF04JobStateTests(unittest.TestCase):
    def _module(self):
        try:
            return importlib.import_module("xp.ai.job_state")
        except ModuleNotFoundError as exc:
            if exc.name == "xp.ai.job_state":
                self.fail("xp.ai.job_state must exist for AF-04 Task 2")
            raise

    def test_unknown_approval_survives_store_reopen_for_same_job(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)

            first = module.JobAIStateStore.for_home(home)
            first.approve_unknown("job-1", "r1", "model-a")

            second = module.JobAIStateStore.for_home(home)

            self.assertTrue(
                second.is_unknown_approved(
                    "job-1",
                    "r1",
                    "model-a",
                )
            )
            self.assertFalse(
                second.is_unknown_approved(
                    "job-2",
                    "r1",
                    "model-a",
                )
            )
            self.assertFalse(
                second.is_unknown_approved(
                    "job-1",
                    "r1",
                    "model-b",
                )
            )

    def test_completed_job_expires_unknown_approval(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            store = module.JobAIStateStore.for_home(Path(td))

            store.approve_unknown("job-1", "r1", "model-a")
            state = store.complete("job-1")

            self.assertTrue(state.completed)
            self.assertIsNone(state.approved_unknown)
            self.assertFalse(
                store.is_unknown_approved(
                    "job-1",
                    "r1",
                    "model-a",
                )
            )

    def test_active_model_survives_store_reopen(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)

            first = module.JobAIStateStore.for_home(home)
            first.set_active_model("job-1", "r1", "model-a")

            second = module.JobAIStateStore.for_home(home)
            state = second.get("job-1")

            self.assertEqual(state.active_route_id, "r1")
            self.assertEqual(state.active_model, "model-a")
            self.assertFalse(state.completed)

    def test_model_switch_records_previous_and_new_model(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            store = module.JobAIStateStore.for_home(Path(td))

            store.set_active_model("job-1", "r1", "model-a")
            state = store.switch_model(
                "job-1",
                new_route_id="r2",
                new_model="model-b",
                reason="hasil kurang sesuai",
            )

            self.assertEqual(state.active_route_id, "r2")
            self.assertEqual(state.active_model, "model-b")
            self.assertEqual(len(state.switches), 1)

            switch = state.switches[0]
            self.assertEqual(switch.previous_route_id, "r1")
            self.assertEqual(switch.previous_model, "model-a")
            self.assertEqual(switch.new_route_id, "r2")
            self.assertEqual(switch.new_model, "model-b")
            self.assertEqual(
                switch.reason,
                "hasil kurang sesuai",
            )
            self.assertTrue(switch.timestamp)

    def test_state_filename_does_not_embed_raw_job_id(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            store = module.JobAIStateStore.for_home(home)

            raw_job_id = "../../sensitive job name"
            store.set_active_model(
                raw_job_id,
                "r1",
                "model-a",
            )

            files = tuple(store.root.glob("*.json"))

            self.assertEqual(len(files), 1)
            self.assertNotIn("sensitive", files[0].name)
            self.assertNotIn("..", files[0].name)


if __name__ == "__main__":
    unittest.main()
