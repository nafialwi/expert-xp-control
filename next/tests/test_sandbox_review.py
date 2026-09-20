from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from xp_next.sandbox_review import (
    ReviewStatus,
    VerifierSpec,
    build_review_bundle,
)


def init_repo(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Fixture"],
        check=True,
    )
    (root / "app.txt").write_text("SAFE\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-qm", "baseline"],
        check=True,
    )


class SandboxReviewTests(unittest.TestCase):
    def test_shell_and_network_wrappers_are_rejected(self):
        for executable in ("sh", "bash", "zsh", "curl", "wget", "ssh"):
            with self.subTest(executable=executable):
                with self.assertRaises(ValueError):
                    VerifierSpec(
                        name="unsafe",
                        argv=(executable, "--version"),
                    )

    def test_pass_bundle_captures_changed_files_diff_and_verifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            init_repo(root)
            (root / "proof.txt").write_text("XP_OK\n", encoding="utf-8")

            spec = VerifierSpec(
                name="proof-check",
                argv=(
                    "python",
                    "-c",
                    (
                        "from pathlib import Path; "
                        "assert Path('proof.txt').read_text() == 'XP_OK\\n'"
                    ),
                ),
            )
            bundle = build_review_bundle(root, verifier_specs=(spec,))

            self.assertEqual(bundle.status, ReviewStatus.PASS)
            self.assertEqual(bundle.changed_files, ("proof.txt",))
            self.assertIn("proof.txt", bundle.bounded_diff)
            self.assertIn("+XP_OK", bundle.bounded_diff)
            self.assertFalse(bundle.diff_truncated)
            self.assertEqual(bundle.verifiers[0].status, ReviewStatus.PASS)
            self.assertFalse(bundle.apply_to_original_performed)
            text = bundle.render_text()
            self.assertIn("PASS", text)
            self.assertIn("proof.txt", text)
            self.assertIn("proof-check", text)

    def test_no_explicit_verifier_is_unverified_not_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            init_repo(root)
            (root / "proof.txt").write_text("XP_OK\n", encoding="utf-8")

            bundle = build_review_bundle(root)

            self.assertEqual(bundle.status, ReviewStatus.UNVERIFIED)
            self.assertEqual(bundle.changed_files, ("proof.txt",))
            self.assertIn("No explicit verifier", bundle.summary)

    def test_failing_verifier_fails_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            init_repo(root)
            (root / "proof.txt").write_text("BAD\n", encoding="utf-8")

            bundle = build_review_bundle(
                root,
                verifier_specs=(
                    VerifierSpec(
                        name="always-fail",
                        argv=("python", "-c", "raise SystemExit(7)"),
                    ),
                ),
            )

            self.assertEqual(bundle.status, ReviewStatus.FAIL)
            self.assertEqual(bundle.verifiers[0].returncode, 7)

    def test_verifier_side_effect_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            init_repo(root)
            (root / "proof.txt").write_text("XP_OK\n", encoding="utf-8")

            bundle = build_review_bundle(
                root,
                verifier_specs=(
                    VerifierSpec(
                        name="mutating-verifier",
                        argv=(
                            "python",
                            "-c",
                            "from pathlib import Path; Path('side-effect.txt').write_text('x')",
                        ),
                    ),
                ),
            )

            self.assertEqual(bundle.status, ReviewStatus.FAIL)
            self.assertIn("mutated sandbox", bundle.summary.lower())

    def test_git_remote_fails_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            init_repo(root)
            subprocess.run(
                ["git", "-C", str(root), "remote", "add", "origin", "https://example.invalid/repo.git"],
                check=True,
            )
            (root / "proof.txt").write_text("XP_OK\n", encoding="utf-8")

            bundle = build_review_bundle(root)

            self.assertEqual(bundle.status, ReviewStatus.FAIL)
            self.assertIn("remote", bundle.summary.lower())

    def test_diff_is_bounded_and_marks_truncation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            init_repo(root)
            (root / "large.txt").write_text("A" * 8000 + "\n", encoding="utf-8")

            bundle = build_review_bundle(root, max_diff_chars=500)

            self.assertEqual(bundle.status, ReviewStatus.UNVERIFIED)
            self.assertTrue(bundle.diff_truncated)
            self.assertLessEqual(len(bundle.bounded_diff), 560)
            self.assertIn("TRUNCATED", bundle.bounded_diff)


if __name__ == "__main__":
    unittest.main()
