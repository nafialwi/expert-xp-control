from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from xp_next.project_context import ProjectContextBuilder
from xp_next.project_inspector import ProjectInspector
from xp_next.task_contract import TaskIntent, TaskIntentKind


class ProjectContextTests(unittest.TestCase):
    def test_context_separates_observed_facts_from_inferred_hints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            (root / "package.json").write_text("{}", encoding="utf-8")
            (root / "pyproject.toml").write_text(
                "[project]\nname='fixture'\n",
                encoding="utf-8",
            )
            inspection = ProjectInspector(
                git_fingerprint=lambda path: {
                    "available": False,
                    "inside_work_tree": False,
                    "branch": None,
                    "head": None,
                    "dirty": None,
                }
            ).inspect(root)
            capabilities = {
                "python": {
                    "capability_id": "python",
                    "state": "READY",
                    "executable": "/tools/python",
                    "version": "Python 3.14",
                    "source": "local",
                    "network_used": False,
                }
            }
            task = TaskIntent.read_only(
                goal="Analisis project fixture",
                kind=TaskIntentKind.ANALYZE,
            )
            context = ProjectContextBuilder().build(
                project={
                    "id": "p1",
                    "name": "Fixture",
                    "root_path": str(root),
                    "source_kind": "local",
                },
                inspection=inspection,
                capabilities=capabilities,
                task=task,
            ).as_dict()

            self.assertEqual(context["project"]["id"], "p1")
            self.assertEqual(context["observed"]["markers"]["package_json"], True)
            self.assertEqual(context["observed"]["markers"]["pyproject_toml"], True)
            self.assertNotIn("stack_hints", context["observed"])
            self.assertEqual(context["inferred"]["stack_hints"], ["node", "python"])
            self.assertEqual(context["task"]["risk"], "read")
            self.assertFalse(context["task"]["mutation_allowed"])
            self.assertFalse(context["task"]["network_allowed"])
            self.assertFalse(context["network_used"])

    def test_git_source_identity_is_bounded_and_explicit(self):
        builder = ProjectContextBuilder()
        context = builder.build(
            project={
                "id": "p1",
                "name": "Git Fixture",
                "root_path": "/fixture",
                "source_kind": "git",
            },
            inspection={
                "root": "/fixture",
                "markers": {"git": True},
                "stack_hints": [],
                "git": {
                    "available": True,
                    "inside_work_tree": True,
                    "branch": "main",
                    "head": "a" * 40,
                    "dirty": False,
                },
                "network_used": False,
            },
            capabilities={},
            task=TaskIntent.read_only(
                goal="Inspect",
                kind=TaskIntentKind.INSPECT,
            ),
        ).as_dict()
        self.assertEqual(
            context["source_identity"],
            {
                "kind": "git",
                "branch": "main",
                "head": "a" * 40,
                "dirty": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
