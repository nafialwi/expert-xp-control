from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


class RealProjectContractTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("XP07_EVIDENCE_FILE")
        or (
            os.environ.get("XP07_LEGACY_REPO")
            and os.environ.get("XP07_NEXT_REPO")
            and os.environ.get("XP07_REAL_HOME")
        ),
        "real-project XP+-07 smoke requires evidence or explicit local repo paths",
    )
    def test_legacy_and_next_a_plus_contract(self):
        evidence_path = os.environ.get(
            "XP07_EVIDENCE_FILE"
        )

        if evidence_path:
            data = json.loads(
                Path(evidence_path).read_text(
                    encoding="utf-8"
                )
            )
        else:
            script = Path(
                "scripts/compat-smoke.py"
            ).resolve()
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--legacy",
                    os.environ[
                        "XP07_LEGACY_REPO"
                    ],
                    "--next",
                    os.environ[
                        "XP07_NEXT_REPO"
                    ],
                    "--xp-home",
                    os.environ[
                        "XP07_REAL_HOME"
                    ],
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(
                result.returncode,
                0,
                result.stdout
                + "\n"
                + result.stderr,
            )
            structured = [
                line
                for line
                in result.stdout.splitlines()
                if line.strip().startswith(
                    "{"
                )
            ]
            self.assertTrue(
                structured,
                result.stdout,
            )
            data = json.loads(
                structured[-1]
            )

        for name in (
            "Legacy",
            "Next",
        ):
            zone1 = data["zone1"][name]
            self.assertTrue(
                zone1["match"]
            )
            self.assertEqual(
                zone1["before_sha256"],
                zone1["after_sha256"],
            )
            self.assertFalse(
                zone1[
                    "command_execution_inside_original"
                ]
            )

        legacy = data["legacy"]
        next_row = data["next"]
        proof = data[
            "no_production_call_proof"
        ]

        self.assertEqual(
            legacy["doctor_status"],
            "PROFILE_INCOMPLETE",
        )
        self.assertTrue(
            legacy[
                "protected_branch_rejected"
            ]
        )
        self.assertEqual(
            legacy[
                "production_db_deploy_calls"
            ],
            0,
        )
        self.assertTrue(
            legacy["zone2"][
                "canonical_boundary_unchanged"
            ]
        )

        self.assertTrue(
            next_row["profile_v1"]
        )
        self.assertTrue(
            next_row[
                "postgresql_adapter"
            ]
        )
        self.assertTrue(
            next_row["npm_verify"]
        )
        self.assertTrue(
            next_row["branch_guard"]
        )
        self.assertGreater(
            next_row[
                "checkpoint_history"
            ],
            0,
        )
        self.assertGreater(
            next_row[
                "locked_remote_runs"
            ],
            0,
        )
        self.assertTrue(
            next_row[
                "new_work_package"
            ]
        )
        self.assertTrue(
            next_row[
                "remote_lease_released"
            ]
        )
        self.assertEqual(
            next_row[
                "production_db_deploy_calls"
            ],
            0,
        )
        self.assertTrue(
            next_row["zone2"][
                "canonical_boundary_unchanged"
            ]
        )

        self.assertTrue(
            all(proof.values()),
            proof,
        )
        self.assertTrue(
            proof[
                "no_harness_added_git_exclusions"
            ]
        )

        backfill = data["backfill"]
        self.assertEqual(
            backfill["xp03"]["Legacy"],
            "PROFILE_INCOMPLETE",
        )
        self.assertEqual(
            backfill["xp03"]["Next"],
            "WORK_READY",
        )
        self.assertTrue(
            backfill["xp035"][
                "registry_unchanged"
            ]
        )
        self.assertLess(
            backfill["xp04"][
                "Legacy_ratio"
            ],
            0.35,
        )
        self.assertLess(
            backfill["xp04"][
                "Next_ratio"
            ],
            0.35,
        )


if __name__ == "__main__":
    unittest.main()
