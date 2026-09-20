from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from xp_next.isolated_workspace import (
    IsolationError,
    prepare_isolated_workspace,
    workspace_changed_paths,
)


class IsolatedWorkspaceTests(unittest.TestCase):
    def _git_source(self, base: Path) -> Path:
        source = base / "source"
        source.mkdir()
        (source / "calc.py").write_text(
            "def total(price, qty):\n    return price - qty\n",
            encoding="utf-8",
        )
        (source / "test_calc.py").write_text(
            "import unittest\n"
            "from calc import total\n\n"
            "class CalcTest(unittest.TestCase):\n"
            "    def test_total(self):\n"
            "        self.assertEqual(total(10, 3), 30)\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q", str(source)], check=True)
        subprocess.run(
            ["git", "-C", str(source), "config", "user.email", "fixture@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(source), "config", "user.name", "Fixture"],
            check=True,
        )
        subprocess.run(["git", "-C", str(source), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(source), "commit", "-qm", "baseline"],
            check=True,
        )
        return source

    def test_prepare_creates_clean_fresh_git_workspace_without_remote(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._git_source(base)
            original_head = subprocess.check_output(
                ["git", "-C", str(source), "rev-parse", "HEAD"],
                text=True,
            ).strip()
            isolated = prepare_isolated_workspace(
                source,
                base / "sandbox",
                job_id="job-1",
            )
            self.assertTrue((isolated.project / "calc.py").is_file())
            self.assertTrue(isolated.home.is_dir())
            self.assertTrue(isolated.tmp.is_dir())
            self.assertEqual(workspace_changed_paths(isolated.project), ())
            remotes = subprocess.check_output(
                ["git", "-C", str(isolated.project), "remote"],
                text=True,
            ).strip()
            self.assertEqual(remotes, "")
            after_head = subprocess.check_output(
                ["git", "-C", str(source), "rev-parse", "HEAD"],
                text=True,
            ).strip()
            self.assertEqual(after_head, original_head)
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(source), "status", "--porcelain"],
                    text=True,
                ),
                "",
            )

    def test_sensitive_files_are_not_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._git_source(base)
            (source / ".env").write_text("SECRET=do-not-copy\n", encoding="utf-8")
            isolated = prepare_isolated_workspace(
                source,
                base / "sandbox",
                job_id="job-2",
            )
            self.assertFalse((isolated.project / ".env").exists())

    def test_symlink_in_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._git_source(base)
            (source / "link").symlink_to(source / "calc.py")
            with self.assertRaises(IsolationError):
                prepare_isolated_workspace(
                    source,
                    base / "sandbox",
                    job_id="job-3",
                )

    def test_workspace_changed_paths_preserves_spaces_and_split_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            source.mkdir()
            (source / "old name.txt").write_text("old\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "init", "-q"], check=True)
            subprocess.run(
                ["git", "-C", str(source), "config", "user.email", "fixture@example.invalid"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(source), "config", "user.name", "Fixture"],
                check=True,
            )
            subprocess.run(["git", "-C", str(source), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(source), "commit", "-qm", "baseline"],
                check=True,
            )
            (source / "old name.txt").rename(source / "new name.txt")
            self.assertEqual(
                workspace_changed_paths(source),
                ("new name.txt", "old name.txt"),
            )

    def test_workspace_diff_detects_only_sandbox_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._git_source(base)
            original = (source / "calc.py").read_bytes()
            isolated = prepare_isolated_workspace(
                source,
                base / "sandbox",
                job_id="job-4",
            )
            (isolated.project / "calc.py").write_text(
                "def total(price, qty):\n    return price * qty\n",
                encoding="utf-8",
            )
            self.assertEqual(workspace_changed_paths(isolated.project), ("calc.py",))
            self.assertEqual((source / "calc.py").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
