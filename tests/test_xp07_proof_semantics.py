from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path("scripts/compat-smoke.py").resolve()


def _load_smoke():
    spec = importlib.util.spec_from_file_location(
        "xp07_a_plus_proof_smoke",
        SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load compat-smoke.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class XP07APlusProofSemanticsTests(unittest.TestCase):
    def test_no_production_proof_uses_positive_boolean_assertions(self):
        smoke = _load_smoke()

        # Read the source-level contract rather than invoking the expensive
        # real-project smoke. The complete runtime smoke is executed later
        # by the one-run gate.
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn(
            '"no_harness_added_git_exclusions": True',
            source,
        )
        self.assertNotIn(
            '"harness_added_git_exclusions": False',
            source,
        )

        expected_positive_keys = {
            "zone1_originals_plain_read_copy_only",
            "source_remotes_replaced_with_local_temp_remotes",
            "control_remotes_local_temp_only",
            "database_credentials_removed",
            "postgres_apply_and_sql_test_methods_guarded",
            "deployment_policy_required_disabled",
            "no_harness_added_git_exclusions",
        }
        for key in expected_positive_keys:
            self.assertIn(
                f'"{key}": True',
                source,
            )


if __name__ == "__main__":
    unittest.main()
