from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from xp.bundle import BundleBuilder


class BundleV2Tests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "project"
        repo.mkdir()
        (repo / ".git").mkdir()
        xp = repo / ".xp"
        xp.mkdir()
        (xp / "project.json").write_text(
            json.dumps(
                {
                    "profile_version": 1,
                    "project_id": "fixture",
                    "name": "Fixture",
                    "runtimes": ["node"],
                    "source_adapter": "git",
                    "database_adapter": None,
                    "verify_adapter": "npm-script",
                    "deployment_adapter": None,
                    "metadata": {},
                }
            ),
            encoding="utf-8",
        )
        (xp / "policies.json").write_text(
            json.dumps(
                {
                    "source_verify": [{"adapter": "node", "script": "verify"}],
                    "protected_branches": ["main"],
                    "allowed_branch_prefixes": ["work/"],
                }
            ),
            encoding="utf-8",
        )
        (xp / "compatibility.json").write_text(
            json.dumps({"required_commands": ["git", "node", "npm"]}),
            encoding="utf-8",
        )
        docs = repo / "docs" / "blueprint"
        docs.mkdir(parents=True)
        (docs / "15_WORKFLOW_PROFILE.md").write_text(
            "workflow\n" * 3000,
            encoding="utf-8",
        )
        return repo

    def _engine(self, root: Path) -> Path:
        engine = root / "engine"
        engine.mkdir()
        for index in range(8):
            (engine / f"module_{index}.py").write_text(
                ("def f():\n    return 'engine-source'\n" * 1500),
                encoding="utf-8",
            )
        return engine

    def test_deep_is_built_first_and_contains_full_engine_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = self._repo(root)
            engine = self._engine(root)
            output = root / "out"
            builder = BundleBuilder(root, engine_root=engine)

            deep = builder.build(repo, deep=True, output_dir=output)
            compact = builder.build(repo, deep=False, output_dir=output)

            deep_text = deep.path.read_text(encoding="utf-8")
            compact_text = compact.path.read_text(encoding="utf-8")

            self.assertEqual(deep.mode, "DEEP")
            self.assertEqual(compact.mode, "COMPACT")
            self.assertIn("##### FILE: module_0.py #####", deep_text)
            self.assertNotIn("##### FILE: module_0.py #####", compact_text)
            self.assertIn("OMITTED IN COMPACT MODE", compact_text)

    def test_compact_is_under_35_percent_of_deep(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = self._repo(root)
            engine = self._engine(root)
            builder = BundleBuilder(root, engine_root=engine)

            deep = builder.build(repo, deep=True, output_dir=root / "out")
            compact = builder.build(repo, deep=False, output_dir=root / "out")

            self.assertLess(
                compact.size_bytes,
                deep.size_bytes * 0.35,
                (compact.size_bytes, deep.size_bytes),
            )

    def test_compact_preserves_core_context_and_schema(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = self._repo(root)
            builder = BundleBuilder(root, engine_root=self._engine(root))

            compact = builder.build(repo, output_dir=root / "out")
            text = compact.path.read_text(encoding="utf-8")

            self.assertIn("===== PROFILE (.xp/project.json) =====", text)
            self.assertIn("===== POLICIES (.xp/policies.json) =====", text)
            self.assertIn("===== COMPATIBILITY (.xp/compatibility.json) =====", text)
            self.assertIn("===== PROJECT DOCTOR =====", text)
            self.assertIn("===== XP SCHEMA =====", text)
            self.assertIn("===== CHECKPOINTS TERKUNCI (via XP) =====", text)

    def test_build_does_not_mutate_project(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = self._repo(root)
            builder = BundleBuilder(root, engine_root=self._engine(root))

            before = {
                path.relative_to(repo).as_posix(): path.read_bytes()
                for path in repo.rglob("*")
                if path.is_file()
            }
            builder.build(repo, deep=True, output_dir=root / "out")
            builder.build(repo, deep=False, output_dir=root / "out")
            after = {
                path.relative_to(repo).as_posix(): path.read_bytes()
                for path in repo.rglob("*")
                if path.is_file()
            }

            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
