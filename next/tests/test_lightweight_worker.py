from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from xp_next.lightweight_worker import LightweightLocalWorker
from xp_next.worker_contract import WorkerRequest, WorkerStatus


class LightweightLocalWorkerTests(unittest.TestCase):
    def _workspace(self, base: Path) -> tuple[Path, Path]:
        root = base / "workspace"
        project = root / "project"
        project.mkdir(parents=True)
        return root, project

    def _request(self, root: Path, project: Path, payload: object) -> WorkerRequest:
        prompt = payload if isinstance(payload, str) else json.dumps(payload)
        return WorkerRequest(
            job_id="lightweight-test",
            prompt=prompt,
            workspace_root=root,
            cwd=project,
        )

    def test_readiness_is_local_deterministic_and_model_free(self):
        ready = LightweightLocalWorker().readiness()
        self.assertTrue(ready.ready)
        self.assertEqual(ready.backend_id, "lightweight_local")
        self.assertEqual(ready.model_transport, "none")
        self.assertIn("direct_file_io", ready.containment)

    def test_replace_text_changes_only_isolated_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, project = self._workspace(base)
            target = project / "app.txt"
            target.write_text("SAFE\n", encoding="utf-8")

            result = LightweightLocalWorker().run(
                self._request(
                    root,
                    project,
                    {
                        "operation": "replace_text",
                        "path": "app.txt",
                        "expected_text": "SAFE\n",
                        "new_text": "CHANGED\n",
                    },
                )
            )

            self.assertEqual(result.status, WorkerStatus.COMPLETED)
            self.assertEqual(target.read_text(encoding="utf-8"), "CHANGED\n")
            self.assertFalse(result.apply_to_original_performed)

    def test_create_text_requires_new_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, project = self._workspace(base)
            worker = LightweightLocalWorker()
            request = self._request(
                root,
                project,
                {
                    "operation": "create_text",
                    "path": "note.txt",
                    "new_text": "hello\n",
                },
            )
            first = worker.run(request)
            second = worker.run(request)

            self.assertEqual(first.status, WorkerStatus.COMPLETED)
            self.assertEqual(second.status, WorkerStatus.NEEDS_ATTENTION)
            self.assertEqual((project / "note.txt").read_text(), "hello\n")

    def test_plain_language_prompt_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, project = self._workspace(Path(tmp))
            result = LightweightLocalWorker().run(
                self._request(root, project, "please change app.txt")
            )
            self.assertEqual(result.status, WorkerStatus.NEEDS_ATTENTION)
            self.assertIn("explicit JSON operation", result.detail)

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, project = self._workspace(base)
            result = LightweightLocalWorker().run(
                self._request(
                    root,
                    project,
                    {
                        "operation": "create_text",
                        "path": "../escape.txt",
                        "new_text": "bad",
                    },
                )
            )
            self.assertEqual(result.status, WorkerStatus.NEEDS_ATTENTION)
            self.assertFalse((root / "escape.txt").exists())

    def test_sensitive_and_git_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, project = self._workspace(Path(tmp))
            worker = LightweightLocalWorker()
            for path in (".env", ".git/config"):
                with self.subTest(path=path):
                    result = worker.run(
                        self._request(
                            root,
                            project,
                            {
                                "operation": "create_text",
                                "path": path,
                                "new_text": "bad",
                            },
                        )
                    )
                    self.assertEqual(result.status, WorkerStatus.NEEDS_ATTENTION)

    def test_expected_text_mismatch_fails_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, project = self._workspace(Path(tmp))
            target = project / "app.txt"
            target.write_text("SAFE\n", encoding="utf-8")

            result = LightweightLocalWorker().run(
                self._request(
                    root,
                    project,
                    {
                        "operation": "replace_text",
                        "path": "app.txt",
                        "expected_text": "OTHER\n",
                        "new_text": "CHANGED\n",
                    },
                )
            )
            self.assertEqual(result.status, WorkerStatus.NEEDS_ATTENTION)
            self.assertEqual(target.read_text(), "SAFE\n")

    def test_symlink_target_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, project = self._workspace(base)
            outside = base / "outside.txt"
            outside.write_text("SAFE\n")
            (project / "link.txt").symlink_to(outside)

            result = LightweightLocalWorker().run(
                self._request(
                    root,
                    project,
                    {
                        "operation": "replace_text",
                        "path": "link.txt",
                        "expected_text": "SAFE\n",
                        "new_text": "CHANGED\n",
                    },
                )
            )
            self.assertEqual(result.status, WorkerStatus.NEEDS_ATTENTION)
            self.assertEqual(outside.read_text(), "SAFE\n")


if __name__ == "__main__":
    unittest.main()
