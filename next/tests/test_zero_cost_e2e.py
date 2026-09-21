from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

from xp_next.hermes_worker import HermesLocalWorker
from xp_next.local_qwen import LocalQwenAdapter
from xp_next.lightweight_worker import LightweightLocalWorker
from xp_next.planner import BoundedReadOnlyPlanner
from xp_next.project_service import ProjectService
from xp_next.runtime_paths import RuntimePaths
from xp_next.sandbox_review import ReviewStatus, VerifierSpec
from xp_next.state_store import StateStore
from xp_next.zero_cost_e2e import (
    HumanApproval,
    HumanReviewDecision,
    ReviewAction,
    ZeroCostE2EService,
)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def init_source(root: Path) -> str:
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Fixture")
    (root / "app.txt").write_text("SAFE\n", encoding="utf-8")
    (root / "WORK_ITEM.md").write_text(
        "Change app.txt from SAFE to CHANGED.\n",
        encoding="utf-8",
    )
    git(root, "add", ".")
    git(root, "commit", "-qm", "baseline")
    return git(root, "rev-parse", "HEAD")


class LocalFixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send(self, payload: dict[str, object]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._send({"status": "ok"})
            return
        if self.path == "/props":
            self._send({"default_generation_settings": {"n_ctx": 65536}})
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        request = json.loads(raw.decode("utf-8"))
        assert request["stream"] is False
        assert request["model"] == "qwen-fixture-local"
        self._send(
            {
                "model": "qwen-fixture-local",
                "choices": [
                    {
                        "message": {
                            "content": (
                                "The bounded fixture context supports the requested "
                                "app.txt change and requires local verification."
                            )
                        }
                    }
                ],
            }
        )


class LoopbackFixtureServer:
    def __enter__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), LocalFixtureHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def write_fixture_hermes(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
from pathlib import Path
Path("app.txt").write_text("CHANGED\\n", encoding="utf-8")
print("fixture hermes changed app.txt")
""",
        encoding="utf-8",
    )
    path.chmod(0o700)


class ZeroCostE2ETests(unittest.TestCase):
    def test_complete_fixture_flow_is_local_reviewed_applied_and_stateful(self):
        with tempfile.TemporaryDirectory() as tmp, LoopbackFixtureServer() as server:
            base = Path(tmp)
            source = base / "source"
            original_head = init_source(source)
            fake_hermes = base / "hermes"
            write_fixture_hermes(fake_hermes)

            paths = RuntimePaths.resolve(base / "runtime").ensure()
            with StateStore(paths.database) as store:
                projects = ProjectService(store)
                projects.register(
                    "fixture",
                    "Fixture Project",
                    source,
                    source_kind="git",
                )

                reasoner = LocalQwenAdapter(
                    base_url=server.base_url,
                    model="qwen-fixture-local",
                    timeout=5,
                )
                worker = HermesLocalWorker(
                    binary=str(fake_hermes),
                    base_url=f"{server.base_url}/v1",
                    model="qwen-fixture-local",
                    context_length=65536,
                    timeout=5,
                )
                service = ZeroCostE2EService(
                    store=store,
                    projects=projects,
                    paths=paths,
                    reasoner=reasoner,
                    planner=BoundedReadOnlyPlanner(),
                    worker=worker,
                )

                verifier = VerifierSpec(
                    name="fixture-content",
                    argv=(
                        "python",
                        "-c",
                        (
                            "from pathlib import Path; "
                            "assert Path('app.txt').read_text() == 'CHANGED\\n'"
                        ),
                    ),
                )

                review_seen: dict[str, object] = {}

                def human_review(bundle):
                    self.assertEqual(bundle.status, ReviewStatus.PASS)
                    self.assertEqual(bundle.changed_files, ("app.txt",))
                    self.assertIn("CHANGED", bundle.bounded_diff)
                    review_seen["fingerprint"] = bundle.change_fingerprint
                    return HumanReviewDecision(
                        action=ReviewAction.APPLY,
                        approved_change_fingerprint=bundle.change_fingerprint,
                    )

                result = service.run(
                    job_id="cp08a-e2e",
                    project_id="fixture",
                    goal="Apply the bounded fixture work item using only local capabilities.",
                    worker_prompt="Read WORK_ITEM.md and make exactly that change.",
                    verifier_specs=(verifier,),
                    sandbox_write_approval=HumanApproval(granted=True),
                    review_decider=human_review,
                )

                self.assertEqual(result.job_state, "COMPLETED")
                self.assertEqual(result.reasoning_status, "COMPLETED")
                self.assertEqual(result.plan_status, "READY")
                self.assertEqual(result.worker_status, "COMPLETED")
                self.assertEqual(result.review_status, "PASS")
                self.assertEqual(result.apply_status, "APPLIED")
                self.assertIsNotNone(result.recovery_ref)
                self.assertIn("fingerprint", review_seen)

                self.assertEqual((source / "app.txt").read_text(), "CHANGED\n")
                self.assertEqual(git(source, "rev-parse", "HEAD"), original_head)
                self.assertEqual(git(source, "status", "--short"), "M app.txt")
                self.assertEqual(git(source, "remote"), "")

                approvals = store.list_approvals("cp08a-e2e")
                self.assertEqual(
                    [(x["approval_class"], x["granted"]) for x in approvals],
                    [("sandbox_write", 1), ("apply_original", 1)],
                )

                activities = store.list_activities("cp08a-e2e")
                self.assertGreaterEqual(len(activities), 9)
                self.assertTrue(all(x["live"] == 0 for x in activities))
                self.assertIn("local_qwen", {x["processor"] for x in activities})
                self.assertIn("hermes", {x["processor"] for x in activities})
                summaries = "\n".join(str(x["summary"]) for x in activities)
                self.assertNotIn("chain-of-thought", summaries.lower())

                recovery = store.list_recovery_points(job_id="cp08a-e2e")
                self.assertEqual(len(recovery), 1)
                self.assertEqual(recovery[0]["project_id"], "fixture")
                self.assertEqual(recovery[0]["source_ref"], result.recovery_ref)


    def test_complete_fixture_flow_with_lightweight_worker(self):
        with tempfile.TemporaryDirectory() as tmp, LoopbackFixtureServer() as server:
            base = Path(tmp)
            source = base / "source"
            original_head = init_source(source)

            paths = RuntimePaths.resolve(base / "runtime").ensure()
            with StateStore(paths.database) as store:
                projects = ProjectService(store)
                projects.register(
                    "fixture-light",
                    "Fixture Light",
                    source,
                    source_kind="git",
                )

                reasoner = LocalQwenAdapter(
                    base_url=server.base_url,
                    model="qwen-fixture-local",
                    timeout=5,
                )
                worker = LightweightLocalWorker()
                service = ZeroCostE2EService(
                    store=store,
                    projects=projects,
                    paths=paths,
                    reasoner=reasoner,
                    planner=BoundedReadOnlyPlanner(),
                    worker=worker,
                )

                verifier = VerifierSpec(
                    name="fixture-content",
                    argv=(
                        "python",
                        "-c",
                        (
                            "from pathlib import Path; "
                            "assert Path('app.txt').read_text() == 'CHANGED\\n'"
                        ),
                    ),
                )

                def human_review(bundle):
                    self.assertEqual(bundle.status, ReviewStatus.PASS)
                    self.assertEqual(bundle.changed_files, ("app.txt",))
                    return HumanReviewDecision(
                        action=ReviewAction.APPLY,
                        approved_change_fingerprint=bundle.change_fingerprint,
                    )

                worker_prompt = json.dumps(
                    {
                        "operation": "replace_text",
                        "path": "app.txt",
                        "expected_text": "SAFE\n",
                        "new_text": "CHANGED\n",
                    }
                )
                result = service.run(
                    job_id="cp08d-lightweight-e2e",
                    project_id="fixture-light",
                    goal="Apply one explicit bounded text replacement locally.",
                    worker_prompt=worker_prompt,
                    verifier_specs=(verifier,),
                    sandbox_write_approval=HumanApproval(granted=True),
                    review_decider=human_review,
                )

                self.assertEqual(result.job_state, "COMPLETED")
                self.assertEqual(result.worker_status, "COMPLETED")
                self.assertEqual(result.review_status, "PASS")
                self.assertEqual(result.apply_status, "APPLIED")
                self.assertEqual((source / "app.txt").read_text(), "CHANGED\n")
                self.assertEqual(git(source, "rev-parse", "HEAD"), original_head)

                activities = store.list_activities("cp08d-lightweight-e2e")
                processors = {x["processor"] for x in activities}
                self.assertIn("lightweight_local", processors)
                self.assertNotIn("hermes", processors)

    def test_nonhuman_approval_is_rejected(self):
        with self.assertRaises(ValueError):
            HumanApproval(granted=True, reviewer="automatic")
        with self.assertRaises(ValueError):
            HumanReviewDecision(
                action=ReviewAction.APPLY,
                approved_change_fingerprint="abc",
                reviewer="automatic",
            )


if __name__ == "__main__":
    unittest.main()
