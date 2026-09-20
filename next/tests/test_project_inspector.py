from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from xp_next.project_inspector import ProjectInspector


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class ProjectInspectorTests(unittest.TestCase):
    def test_detects_markers_and_stack_hints_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            (root / ".git").mkdir()
            (root / "package.json").write_text('{"name":"fixture"}', encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
            (root / "requirements.txt").write_text("pytest\n", encoding="utf-8")
            (root / "tests").mkdir()
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")

            before = tree_digest(root)

            inspector = ProjectInspector(
                git_fingerprint=lambda path: {
                    "available": True,
                    "inside_work_tree": True,
                    "branch": "main",
                    "head": "a" * 40,
                    "dirty": False,
                }
            )
            facts = inspector.inspect(root)

            after = tree_digest(root)
            self.assertEqual(before, after)
            self.assertEqual(facts["root"], str(root.resolve()))
            self.assertTrue(facts["markers"]["git"])
            self.assertTrue(facts["markers"]["package_json"])
            self.assertTrue(facts["markers"]["pyproject_toml"])
            self.assertTrue(facts["markers"]["requirements_txt"])
            self.assertTrue(facts["markers"]["tests_dir"])
            self.assertTrue(facts["markers"]["src_dir"])
            self.assertEqual(facts["stack_hints"], ["node", "python"])
            self.assertEqual(facts["git"]["branch"], "main")
            self.assertFalse(facts["git"]["dirty"])
            self.assertFalse(facts["network_used"])

    def test_plain_directory_reports_no_false_stack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "plain"
            root.mkdir()
            facts = ProjectInspector(
                git_fingerprint=lambda path: {
                    "available": False,
                    "inside_work_tree": False,
                    "branch": None,
                    "head": None,
                    "dirty": None,
                }
            ).inspect(root)
            self.assertEqual(facts["stack_hints"], [])
            self.assertFalse(facts["markers"]["git"])
            self.assertFalse(facts["markers"]["package_json"])
            self.assertFalse(facts["markers"]["pyproject_toml"])

    def test_marker_scan_is_bounded_to_known_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            deep = root / "vendor" / "huge" / "tree"
            deep.mkdir(parents=True)
            (deep / "package.json").write_text("{}", encoding="utf-8")
            facts = ProjectInspector(
                git_fingerprint=lambda path: {
                    "available": False,
                    "inside_work_tree": False,
                    "branch": None,
                    "head": None,
                    "dirty": None,
                }
            ).inspect(root)
            self.assertFalse(facts["markers"]["package_json"])
            self.assertEqual(facts["stack_hints"], [])


if __name__ == "__main__":
    unittest.main()
