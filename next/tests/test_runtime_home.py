from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from xp_next.runtime_paths import RuntimePathError, RuntimePaths


class RuntimePathsTests(unittest.TestCase):
    def test_explicit_home_is_canonicalized_and_layout_is_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            requested = Path(tmp) / "home" / ".." / "xp-home"
            paths = RuntimePaths.resolve(requested)
            self.assertEqual(paths.root, (Path(tmp) / "xp-home").resolve())
            self.assertEqual(paths.database, paths.root / "state" / "xp-next.sqlite3")
            self.assertEqual(paths.artifacts, paths.root / "artifacts")
            self.assertEqual(paths.workspaces, paths.root / "workspaces")
            self.assertEqual(paths.logs, paths.root / "logs")

    def test_environment_override_beats_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"XP_NEXT_HOME": tmp}, clear=False):
                paths = RuntimePaths.resolve()
            self.assertEqual(paths.root, Path(tmp).resolve())

    def test_ensure_creates_only_expected_runtime_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "xp"
            paths = RuntimePaths.resolve(root)
            paths.ensure()
            self.assertTrue(paths.state.is_dir())
            self.assertTrue(paths.artifacts.is_dir())
            self.assertTrue(paths.workspaces.is_dir())
            self.assertTrue(paths.logs.is_dir())
            self.assertFalse(paths.database.exists())

    def test_symlink_runtime_root_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "target"
            target.mkdir()
            link = base / "xp-link"
            link.symlink_to(target, target_is_directory=True)
            paths = RuntimePaths.resolve(link)
            with self.assertRaises(RuntimePathError):
                paths.ensure()


if __name__ == "__main__":
    unittest.main()
