from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from xp_next.service import review_sandbox
from xp_next.sandbox_review import VerifierSpec


class ReviewServiceTests(unittest.TestCase):
    def test_service_returns_human_and_structured_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(root), "config", "user.name", "Fixture"],
                check=True,
            )
            (root / "a.txt").write_text("one\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(root), "commit", "-qm", "baseline"],
                check=True,
            )
            (root / "a.txt").write_text("two\n", encoding="utf-8")

            result = review_sandbox(
                root,
                verifier_specs=(
                    VerifierSpec(
                        name="content-check",
                        argv=(
                            "python",
                            "-c",
                            "from pathlib import Path; assert Path('a.txt').read_text() == 'two\\n'",
                        ),
                    ),
                ),
            )

            self.assertEqual(result["bundle"]["status"], "PASS")
            self.assertIn("a.txt", result["human_review"])
            self.assertFalse(result["bundle"]["apply_to_original_performed"])


if __name__ == "__main__":
    unittest.main()
