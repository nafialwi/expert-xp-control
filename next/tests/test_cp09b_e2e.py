from __future__ import annotations

import http.client
import json
from http.cookies import SimpleCookie
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest

from next.tests.test_zero_cost_e2e import (
    LoopbackFixtureServer,
    git,
    init_source,
)
from xp_next.local_qwen import LocalQwenAdapter
from xp_next.lightweight_worker import LightweightLocalWorker
from xp_next.planner import BoundedReadOnlyPlanner
from xp_next.project_service import ProjectService
from xp_next.runtime_paths import RuntimePaths
from xp_next.state_store import StateStore
from xp_next.visual_gateway import make_visual_gateway
from xp_next.work_session_service import WorkSessionService
from xp_next.worker_selection import ResourceSnapshot, WorkerSelector


class CountingWorker:
    def __init__(self):
        self.inner = LightweightLocalWorker()
        self.run_count = 0

    def readiness(self):
        return self.inner.readiness()

    def run(self, *args, **kwargs):
        self.run_count += 1
        return self.inner.run(*args, **kwargs)


def operation_prompt() -> str:
    return json.dumps(
        {
            "operation": "replace_text",
            "path": "app.txt",
            "expected_text": "SAFE\n",
            "new_text": "CHANGED\n",
        }
    )


def project_verifier_script(*, failing: bool = False) -> str:
    if failing:
        code = "raise SystemExit(7)"
    else:
        code = (
            "from pathlib import Path; "
            "assert Path('app.txt').read_text() == 'CHANGED\\n'"
        )
    return f'{sys.executable} -c "{code}"'


def install_project_verifier(
    root: Path,
    *,
    failing: bool = False,
) -> None:
    (root / "package.json").write_text(
        json.dumps(
            {
                "private": True,
                "scripts": {
                    "verify": project_verifier_script(failing=failing),
                },
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    git(root, "add", "package.json")
    git(root, "commit", "-qm", "fixture verifier")


class RealGatewayEnvironment:
    def __init__(
        self,
        base: Path,
        reasoning_server: LoopbackFixtureServer,
        *,
        worker: CountingWorker | None = None,
        reopen: bool = False,
    ):
        self.base = base
        self.source = base / "source"
        if not reopen:
            init_source(self.source)
            install_project_verifier(self.source)

        self.paths = RuntimePaths.resolve(base / "runtime").ensure()
        self.store = StateStore(self.paths.database)
        self.projects = ProjectService(self.store)
        if not reopen:
            self.projects.register(
                "fixture",
                "Fixture Project",
                self.source,
                source_kind="git",
            )
            self.projects.switch("fixture")

        self.worker = worker or CountingWorker()
        self.workers = {"lightweight_local": self.worker}
        self.selector = WorkerSelector(self.workers)
        self.service = WorkSessionService(
            store=self.store,
            projects=self.projects,
            paths=self.paths,
            reasoner=LocalQwenAdapter(
                base_url=reasoning_server.base_url,
                model="qwen-fixture-local",
                timeout=5,
            ),
            planner=BoundedReadOnlyPlanner(),
            workers=self.workers,
            selector=self.selector,
            resource_probe=lambda: ResourceSnapshot(
                available_memory_mb=512,
                logical_cpus=2,
                source="cp09b-e2e",
            ),
        )
        self.server = make_visual_gateway(
            host="127.0.0.1",
            port=0,
            service=self.service,
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()
        self.host = "127.0.0.1"
        self.port = int(self.server.server_port)
        self.origin = f"http://{self.host}:{self.port}"
        self.cookie = self._obtain_cookie()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.store.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, object] | str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], object]:
        connection = http.client.HTTPConnection(
            self.host,
            self.port,
            timeout=8,
        )
        final_headers = dict(headers or {})
        payload: str | None = None
        if isinstance(body, dict):
            payload = json.dumps(body)
            final_headers.setdefault(
                "Content-Type",
                "application/json",
            )
        elif isinstance(body, str):
            payload = body

        connection.request(
            method,
            path,
            body=payload,
            headers=final_headers,
        )
        response = connection.getresponse()
        data = response.read()
        content_type = response.getheader("Content-Type", "")
        decoded: object
        if data and content_type.startswith("application/json"):
            decoded = json.loads(data.decode("utf-8"))
        else:
            decoded = data.decode("utf-8")
        result_headers = dict(response.getheaders())
        status = response.status
        connection.close()
        return status, result_headers, decoded

    def _obtain_cookie(self) -> str:
        status, headers, _ = self.request("GET", "/")
        if status != 200:
            raise AssertionError(f"gateway root returned {status}")
        cookie = SimpleCookie()
        cookie.load(headers["Set-Cookie"])
        return f"xp_session={cookie['xp_session'].value}"

    def mutation_headers(
        self,
        *,
        origin: str | None = None,
        cookie: str | None = None,
    ) -> dict[str, str]:
        return {
            "Origin": self.origin if origin is None else origin,
            "Cookie": self.cookie if cookie is None else cookie,
            "Content-Type": "application/json",
        }

    def post(
        self,
        path: str,
        body: dict[str, object],
        *,
        origin: str | None = None,
        cookie: str | None = None,
    ) -> tuple[int, dict[str, object]]:
        status, _, result = self.request(
            "POST",
            path,
            body=body,
            headers=self.mutation_headers(
                origin=origin,
                cookie=cookie,
            ),
        )
        assert isinstance(result, dict)
        return status, result

    def create(
        self,
        job_id: str,
    ) -> tuple[int, dict[str, object]]:
        return self.post(
            "/api/v2/work-sessions",
            {
                "job_id": job_id,
                "project_id": "fixture",
                "goal": "Change app.txt safely",
                "worker_prompt": operation_prompt(),
            },
        )

    def to_review(
        self,
        job_id: str,
    ) -> dict[str, object]:
        status, created = self.create(job_id)
        if status != 201:
            raise AssertionError((status, created))

        backend = str(created["worker"]["backend_id"])
        revision = int(created["revision"])
        status, confirmed = self.post(
            f"/api/v2/work-sessions/{job_id}/worker-decision",
            {
                "backend_id": backend,
                "approved": True,
                "expected_revision": revision,
            },
        )
        if status != 200:
            raise AssertionError((status, confirmed))

        revision = int(confirmed["revision"])
        status, sandbox = self.post(
            f"/api/v2/work-sessions/{job_id}/sandbox-decision",
            {
                "approved": True,
                "expected_revision": revision,
            },
        )
        if status != 200:
            raise AssertionError((status, sandbox))

        revision = int(sandbox["revision"])
        status, reviewed = self.post(
            f"/api/v2/work-sessions/{job_id}/execute",
            {"expected_revision": revision},
        )
        if status != 200:
            raise AssertionError((status, reviewed))
        return reviewed


class CP09BHTTPAcceptanceTests(unittest.TestCase):
    def test_http_discard_flow_pauses_at_review_and_keeps_original_clean(self):
        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as reasoner:
            env = RealGatewayEnvironment(Path(td), reasoner)
            try:
                reviewed = env.to_review("discard-1")
                self.assertEqual(reviewed["state"], "READY_TO_REVIEW")
                self.assertEqual(
                    (env.source / "app.txt").read_text(encoding="utf-8"),
                    "SAFE\n",
                )
                self.assertEqual(git(env.source, "status", "--short"), "")
                self.assertEqual(env.worker.run_count, 1)

                status, final = env.post(
                    "/api/v2/work-sessions/discard-1/review-decision",
                    {
                        "action": "DISCARD",
                        "fingerprint": reviewed["review"]["change_fingerprint"],
                        "expected_revision": reviewed["revision"],
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(final["state"], "CANCELLED")
                self.assertEqual(final["apply_status"], "DISCARDED")
                self.assertEqual(
                    (env.source / "app.txt").read_text(encoding="utf-8"),
                    "SAFE\n",
                )
                self.assertEqual(git(env.source, "status", "--short"), "")
                self.assertEqual(env.worker.run_count, 1)
            finally:
                env.close()

    def test_http_apply_flow_is_verified_and_records_recovery(self):
        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as reasoner:
            env = RealGatewayEnvironment(Path(td), reasoner)
            try:
                reviewed = env.to_review("apply-1")
                status, final = env.post(
                    "/api/v2/work-sessions/apply-1/review-decision",
                    {
                        "action": "APPLY",
                        "fingerprint": reviewed["review"]["change_fingerprint"],
                        "expected_revision": reviewed["revision"],
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(final["state"], "COMPLETED")
                self.assertEqual(final["apply_status"], "APPLIED")
                self.assertTrue(final["recovery_available"])
                self.assertEqual(
                    (env.source / "app.txt").read_text(encoding="utf-8"),
                    "CHANGED\n",
                )
                recoveries = env.store.list_recovery_points(
                    job_id="apply-1"
                )
                self.assertEqual(len(recoveries), 1)
                self.assertTrue(str(recoveries[0]["source_ref"]).strip())
            finally:
                env.close()

    def test_restart_at_review_resumes_without_worker_rerun(self):
        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as reasoner:
            base = Path(td)
            env = RealGatewayEnvironment(base, reasoner)
            reviewed = env.to_review("restart-1")
            fingerprint = str(
                reviewed["review"]["change_fingerprint"]
            )
            revision = int(reviewed["revision"])
            worker = env.worker
            self.assertEqual(worker.run_count, 1)
            env.close()

            reopened = RealGatewayEnvironment(
                base,
                reasoner,
                worker=worker,
                reopen=True,
            )
            try:
                status, _, loaded_raw = reopened.request(
                    "GET",
                    "/api/v2/work-sessions/restart-1",
                )
                self.assertEqual(status, 200)
                self.assertIsInstance(loaded_raw, dict)
                loaded = loaded_raw
                self.assertEqual(loaded["state"], "READY_TO_REVIEW")
                self.assertEqual(loaded["revision"], revision)

                status, final = reopened.post(
                    "/api/v2/work-sessions/restart-1/review-decision",
                    {
                        "action": "DISCARD",
                        "fingerprint": fingerprint,
                        "expected_revision": revision,
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(final["state"], "CANCELLED")
                self.assertEqual(worker.run_count, 1)
            finally:
                reopened.close()

    def test_dirty_original_is_rejected_as_conflict_before_job_execution(self):
        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as reasoner:
            env = RealGatewayEnvironment(Path(td), reasoner)
            try:
                (env.source / "dirty.txt").write_text(
                    "DIRTY\n",
                    encoding="utf-8",
                )
                status, body = env.create("dirty-1")
                self.assertEqual(status, 409)
                self.assertFalse(body["ok"])
                self.assertEqual(env.worker.run_count, 0)
                with self.assertRaises(Exception):
                    env.store.get_job("dirty-1")
            finally:
                env.close()

    def test_worker_and_sandbox_declines_cancel_without_execution(self):
        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as reasoner:
            env = RealGatewayEnvironment(Path(td), reasoner)
            try:
                status, created = env.create("decline-worker")
                self.assertEqual(status, 201)
                status, declined = env.post(
                    "/api/v2/work-sessions/decline-worker/worker-decision",
                    {
                        "backend_id": created["worker"]["backend_id"],
                        "approved": False,
                        "expected_revision": created["revision"],
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(declined["state"], "CANCELLED")
                self.assertEqual(env.worker.run_count, 0)

                status, created2 = env.create("decline-sandbox")
                self.assertEqual(status, 201)
                status, confirmed = env.post(
                    "/api/v2/work-sessions/decline-sandbox/worker-decision",
                    {
                        "backend_id": created2["worker"]["backend_id"],
                        "approved": True,
                        "expected_revision": created2["revision"],
                    },
                )
                self.assertEqual(status, 200)
                status, declined2 = env.post(
                    "/api/v2/work-sessions/decline-sandbox/sandbox-decision",
                    {
                        "approved": False,
                        "expected_revision": confirmed["revision"],
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(declined2["state"], "CANCELLED")
                self.assertEqual(env.worker.run_count, 0)
                self.assertEqual(
                    (env.source / "app.txt").read_text(encoding="utf-8"),
                    "SAFE\n",
                )
            finally:
                env.close()

    def test_failed_verifier_never_exposes_apply(self):
        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as reasoner:
            env = RealGatewayEnvironment(Path(td), reasoner)
            try:
                install_project_verifier(
                    env.source,
                    failing=True,
                )
                result = env.to_review("verify-fail")
                self.assertEqual(result["state"], "NEEDS_ATTENTION")
                self.assertEqual(result["allowed_actions"], [])
                self.assertEqual(
                    (env.source / "app.txt").read_text(encoding="utf-8"),
                    "SAFE\n",
                )
            finally:
                env.close()

    def test_wrong_fingerprint_and_head_drift_fail_closed(self):
        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as reasoner:
            env = RealGatewayEnvironment(Path(td), reasoner)
            try:
                reviewed = env.to_review("fingerprint-1")
                status, wrong = env.post(
                    "/api/v2/work-sessions/fingerprint-1/review-decision",
                    {
                        "action": "APPLY",
                        "fingerprint": "wrong-fingerprint",
                        "expected_revision": reviewed["revision"],
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(wrong["state"], "NEEDS_ATTENTION")
                self.assertEqual(
                    (env.source / "app.txt").read_text(encoding="utf-8"),
                    "SAFE\n",
                )
            finally:
                env.close()

        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as reasoner:
            env = RealGatewayEnvironment(Path(td), reasoner)
            try:
                reviewed = env.to_review("drift-1")
                (env.source / "drift.txt").write_text(
                    "DRIFT\n",
                    encoding="utf-8",
                )
                git(env.source, "add", "drift.txt")
                git(env.source, "commit", "-qm", "external drift")
                drift_head = git(env.source, "rev-parse", "HEAD")

                status, final = env.post(
                    "/api/v2/work-sessions/drift-1/review-decision",
                    {
                        "action": "APPLY",
                        "fingerprint": reviewed["review"]["change_fingerprint"],
                        "expected_revision": reviewed["revision"],
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(final["state"], "NEEDS_ATTENTION")
                self.assertEqual(
                    (env.source / "app.txt").read_text(encoding="utf-8"),
                    "SAFE\n",
                )
                self.assertEqual(
                    git(env.source, "rev-parse", "HEAD"),
                    drift_head,
                )
            finally:
                env.close()

    def test_missing_sandbox_fails_closed_and_stale_request_is_409(self):
        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as reasoner:
            env = RealGatewayEnvironment(Path(td), reasoner)
            try:
                status, created = env.create("stale-1")
                self.assertEqual(status, 201)
                revision = int(created["revision"])
                payload = {
                    "backend_id": created["worker"]["backend_id"],
                    "approved": True,
                    "expected_revision": revision,
                }
                status, first = env.post(
                    "/api/v2/work-sessions/stale-1/worker-decision",
                    payload,
                )
                self.assertEqual(status, 200)
                status, second = env.post(
                    "/api/v2/work-sessions/stale-1/worker-decision",
                    payload,
                )
                self.assertEqual(status, 409)
                self.assertFalse(second["ok"])
                approvals = [
                    item
                    for item in env.store.list_approvals("stale-1")
                    if item["approval_class"] == "worker_selection"
                ]
                self.assertEqual(len(approvals), 1)
            finally:
                env.close()

        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as reasoner:
            env = RealGatewayEnvironment(Path(td), reasoner)
            try:
                reviewed = env.to_review("missing-sandbox")
                session = env.store.get_work_session("missing-sandbox")
                sandbox_root = Path(
                    str(session["payload"]["sandbox_root"])
                )
                shutil.rmtree(sandbox_root.parent)

                status, result = env.post(
                    "/api/v2/work-sessions/missing-sandbox/review-decision",
                    {
                        "action": "APPLY",
                        "fingerprint": reviewed["review"]["change_fingerprint"],
                        "expected_revision": reviewed["revision"],
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(result["state"], "NEEDS_ATTENTION")
                self.assertEqual(
                    (env.source / "app.txt").read_text(encoding="utf-8"),
                    "SAFE\n",
                )
            finally:
                env.close()

    def test_invalid_origin_or_cookie_is_rejected_before_service_mutation(self):
        with tempfile.TemporaryDirectory() as td, LoopbackFixtureServer() as reasoner:
            env = RealGatewayEnvironment(Path(td), reasoner)
            try:
                body = {
                    "job_id": "blocked-1",
                    "project_id": "fixture",
                    "goal": "blocked",
                    "worker_prompt": operation_prompt(),
                }
                status, result = env.post(
                    "/api/v2/work-sessions",
                    body,
                    origin="http://evil.invalid",
                )
                self.assertEqual(status, 403)
                self.assertFalse(result["ok"])

                status, result = env.post(
                    "/api/v2/work-sessions",
                    body,
                    cookie="xp_session=wrong",
                )
                self.assertEqual(status, 403)
                self.assertFalse(result["ok"])

                with self.assertRaises(Exception):
                    env.store.get_job("blocked-1")
            finally:
                env.close()


if __name__ == "__main__":
    unittest.main()
