from __future__ import annotations

import inspect
import tempfile
import unittest
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from xp.ai.job_state import JobAIStateStore


NOW = datetime(2026, 9, 18, 4, 30, tzinfo=timezone.utc)


class AF04ModelSwitchTests(unittest.TestCase):
    def _module(self):
        import xp.ai.model_switch as module
        return module

    def _store(self, root: Path) -> JobAIStateStore:
        store = JobAIStateStore.for_home(root)
        store.set_active_model(
            "job-1",
            "route-a",
            "model-a",
        )
        return store

    def _record_mismatch(self, store: JobAIStateStore) -> None:
        method = store.record_model_mismatch
        params = inspect.signature(method).parameters
        kwargs = {}

        if "observed_at" in params:
            kwargs["observed_at"] = NOW
        elif "timestamp" in params:
            kwargs["timestamp"] = NOW
        elif "when" in params:
            kwargs["when"] = NOW

        method(
            "job-1",
            route_id="route-a",
            configured_model="model-a",
            served_model="provider-other-model",
            **kwargs,
        )

    def _handoff(self):
        module = self._module()
        return module.ObservableModelHandoff(
            goal="Perbaiki bug transaksi.",
            files=("src/payments.py", "tests/test_payments.py"),
            decisions=("Gunakan jalur validasi yang sudah ada.",),
            results=("Reproduksi bug sudah ditemukan.",),
            errors=("Regression belum dijalankan.",),
            progress=("Test reproduksi sudah tersedia.",),
            next_action="Jalankan perbaikan minimal dan regression.",
        )

    def test_handoff_surface_contains_only_locked_observable_fields(self):
        module = self._module()

        self.assertEqual(
            {field.name for field in fields(module.ObservableModelHandoff)},
            {
                "goal",
                "files",
                "decisions",
                "results",
                "errors",
                "progress",
                "next_action",
            },
        )

    def test_handoff_rejects_hidden_reasoning_markers(self):
        module = self._module()

        for secret_text in (
            "chain_of_thought=SECRET",
            "scratchpad: private notes",
            "reasoning_content hidden",
            "hidden reasoning goes here",
        ):
            with self.subTest(secret_text=secret_text):
                with self.assertRaises(
                    module.ObservableHandoffError
                ):
                    module.ObservableModelHandoff(
                        decisions=(secret_text,),
                    )

    def test_handoff_rejects_non_string_observable_values(self):
        module = self._module()

        with self.assertRaises(module.ObservableHandoffError):
            module.ObservableModelHandoff(
                files=("src/a.py", 123),
            )

    def test_switch_without_explicit_approval_is_blocked_before_state_change(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = self._store(root)
            service = module.ExplicitModelSwitchService(store)

            before = store.get("job-1")

            with self.assertRaises(
                module.ModelSwitchApprovalRequired
            ):
                service.switch(
                    job_id="job-1",
                    new_route_id="route-b",
                    new_model="model-b",
                    approved=False,
                    handoff=self._handoff(),
                    )

            after = store.get("job-1")

        self.assertEqual(before, after)
        self.assertEqual(len(after.switches), 0)

    def test_approved_switch_keeps_same_job_and_records_exact_transition(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = self._store(root)
            service = module.ExplicitModelSwitchService(store)

            result = service.switch(
                job_id="job-1",
                new_route_id="route-b",
                new_model="model-b",
                approved=True,
                handoff=self._handoff(),
                reason="User memilih model lain.",
            )

            reopened = JobAIStateStore.for_home(root)
            state = reopened.get("job-1")

        self.assertEqual(result.job_id, "job-1")
        self.assertEqual(state.job_id, "job-1")
        self.assertEqual(state.active_route_id, "route-b")
        self.assertEqual(state.active_model, "model-b")
        self.assertEqual(len(state.switches), 1)

        switch = state.switches[0]
        self.assertEqual(switch.previous_route_id, "route-a")
        self.assertEqual(switch.previous_model, "model-a")
        self.assertEqual(switch.new_route_id, "route-b")
        self.assertEqual(switch.new_model, "model-b")
        parsed_switch_time = datetime.fromisoformat(switch.timestamp)
        self.assertIsNotNone(parsed_switch_time.tzinfo)
        self.assertIsNotNone(parsed_switch_time.utcoffset())
        self.assertEqual(result.switched_at, switch.timestamp)
        self.assertEqual(
            switch.reason,
            "User memilih model lain.",
        )

        self.assertEqual(result.previous_route_id, "route-a")
        self.assertEqual(result.previous_model, "model-a")
        self.assertEqual(result.new_route_id, "route-b")
        self.assertEqual(result.new_model, "model-b")
        self.assertEqual(result.handoff, self._handoff())

    def test_switch_requires_existing_active_model(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            store = JobAIStateStore.for_home(Path(td))
            service = module.ExplicitModelSwitchService(store)

            with self.assertRaises(
                module.ModelSwitchStateError
            ):
                service.switch(
                    job_id="job-empty",
                    new_route_id="route-b",
                    new_model="model-b",
                    approved=True,
                    handoff=self._handoff(),
                    )

    def test_switch_to_same_route_and_model_is_rejected(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            store = self._store(Path(td))
            service = module.ExplicitModelSwitchService(store)

            with self.assertRaises(
                module.ModelSwitchStateError
            ):
                service.switch(
                    job_id="job-1",
                    new_route_id="route-a",
                    new_model="model-a",
                    approved=True,
                    handoff=self._handoff(),
                    )

            state = store.get("job-1")

        self.assertEqual(len(state.switches), 0)

    def test_completed_job_cannot_switch_model(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            store = self._store(Path(td))
            store.complete("job-1")
            service = module.ExplicitModelSwitchService(store)

            with self.assertRaises(
                module.ModelSwitchStateError
            ):
                service.switch(
                    job_id="job-1",
                    new_route_id="route-b",
                    new_model="model-b",
                    approved=True,
                    handoff=self._handoff(),
                    )

    def test_reason_must_be_observable_not_hidden_reasoning(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            store = self._store(Path(td))
            service = module.ExplicitModelSwitchService(store)

            with self.assertRaises(
                module.ObservableHandoffError
            ):
                service.switch(
                    job_id="job-1",
                    new_route_id="route-b",
                    new_model="model-b",
                    approved=True,
                    handoff=self._handoff(),
                        reason="scratchpad=SECRET",
                )

            state = store.get("job-1")

        self.assertEqual(state.active_model, "model-a")
        self.assertEqual(len(state.switches), 0)

    def test_switch_is_local_only_and_does_not_call_network_or_model(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            store = self._store(Path(td))
            service = module.ExplicitModelSwitchService(store)

            with patch(
                "urllib.request.urlopen",
                side_effect=AssertionError(
                    "model switch must not access network"
                ),
            ):
                result = service.switch(
                    job_id="job-1",
                    new_route_id="route-b",
                    new_model="model-b",
                    approved=True,
                    handoff=self._handoff(),
                    )

        self.assertEqual(result.new_model, "model-b")

    def test_switch_clears_job_scoped_unknown_approval_and_pending_mismatch(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = self._store(root)

            store.approve_unknown(
                "job-1",
                "route-a",
                "model-a",
            )
            self._record_mismatch(store)

            service = module.ExplicitModelSwitchService(store)
            service.switch(
                job_id="job-1",
                new_route_id="route-b",
                new_model="model-b",
                approved=True,
                handoff=self._handoff(),
            )

            state = store.get("job-1")

        self.assertIsNone(state.approved_unknown)
        self.assertIsNone(state.pending_model_mismatch)

    def test_approval_is_per_switch_call_not_persisted_as_blanket_permission(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            store = self._store(Path(td))
            service = module.ExplicitModelSwitchService(store)

            service.switch(
                job_id="job-1",
                new_route_id="route-b",
                new_model="model-b",
                approved=True,
                handoff=self._handoff(),
            )

            with self.assertRaises(
                module.ModelSwitchApprovalRequired
            ):
                service.switch(
                    job_id="job-1",
                    new_route_id="route-c",
                    new_model="model-c",
                    approved=False,
                    handoff=self._handoff(),
                    )

            state = store.get("job-1")

        self.assertEqual(state.active_model, "model-b")
        self.assertEqual(len(state.switches), 1)


if __name__ == "__main__":
    unittest.main()
