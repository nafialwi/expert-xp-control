from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from xp_next.worker_contract import (
    WorkerRequest,
    WorkerStatus,
    WorkerContractError,
)


class WorkerContractTests(unittest.TestCase):
    def test_request_requires_cwd_inside_isolated_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "sandbox"
            cwd = root / "project"
            outside = base / "outside"
            cwd.mkdir(parents=True)
            outside.mkdir()
            with self.assertRaises(WorkerContractError):
                WorkerRequest(
                    job_id="job-1",
                    prompt="fix fixture",
                    workspace_root=root,
                    cwd=outside,
                )

    def test_request_is_explicitly_isolated_write_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sandbox"
            cwd = root / "project"
            cwd.mkdir(parents=True)
            request = WorkerRequest(
                job_id="job-1",
                prompt="fix fixture",
                workspace_root=root,
                cwd=cwd,
            )
            self.assertEqual(request.scope, "isolated_workspace")
            self.assertTrue(request.mutation_allowed)
            self.assertFalse(request.apply_to_original_allowed)
            self.assertFalse(request.production_allowed)

    def test_worker_status_contract_is_small(self):
        self.assertEqual(
            {item.value for item in WorkerStatus},
            {"COMPLETED", "NEEDS_ATTENTION"},
        )


if __name__ == "__main__":
    unittest.main()
