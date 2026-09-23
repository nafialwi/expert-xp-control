from __future__ import annotations

import http.client
import json
import threading
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from http.cookies import SimpleCookie

from xp_next.cli import build_parser, main
from xp_next.job_state import JobState
from xp_next.state_store import StateStoreError
from xp_next.work_session import WorkSessionSnapshot
from xp_next.zero_cost_e2e import ReviewAction
from xp_next.visual_gateway import make_visual_gateway


def snapshot(revision: int = 1, state: str = "AWAITING_APPROVAL") -> WorkSessionSnapshot:
    payload: dict[str, object] = {
        "project_name": "Fixture",
        "worker_selection": {
            "status": "RECOMMENDED",
            "backend_id": "lightweight_local",
            "detail": "bounded operation",
            "resource_snapshot": {
                "available_memory_mb": 512,
                "logical_cpus": 2,
                "source": "fixture",
            },
        },
        "sandbox_approved": None,
        "review": None,
        "apply_status": None,
        "recovery_ref": None,
    }
    if state == JobState.READY_TO_REVIEW.value:
        payload["worker_confirmation"] = {
            "status": "CONFIRMED",
            "backend_id": "lightweight_local",
            "detail": "confirmed",
            "resource_snapshot": {
                "available_memory_mb": 512,
                "logical_cpus": 2,
                "source": "fixture",
            },
            "selection_status": "RECOMMENDED",
        }
        payload["sandbox_approved"] = True
        payload["review"] = {
            "status": "PASS",
            "summary": "verified",
            "changed_files": ["app.txt"],
            "bounded_diff": "diff",
            "diff_truncated": False,
            "change_fingerprint": "abc",
        }
    return WorkSessionSnapshot(
        job={
            "id": "j1",
            "project_id": "p1",
            "user_goal": "goal",
            "state": state,
        },
        session={
            "job_id": "j1",
            "revision": revision,
            "payload": payload,
        },
        activities=(),
    )


class FakeService:
    def __init__(self):
        self.current_revision = 1
        self.execute_side_effects = 0
        self.calls: list[tuple[str, object]] = []

    def visual_snapshot(self):
        return {"product": "XP Next", "status": "READY"}

    def list_visual_projects(self):
        return [{"id": "p1", "name": "Fixture", "active": True}]

    def select_visual_project(self, project_id: str):
        self.calls.append(("select", project_id))
        return {"id": project_id, "name": "Fixture", "active": True}

    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        return snapshot()

    def get(self, job_id: str):
        self.calls.append(("get", job_id))
        return snapshot(revision=self.current_revision)

    def decide_worker(self, job_id: str, **kwargs):
        self.calls.append(("worker", kwargs))
        return snapshot(revision=self.current_revision + 1)

    def decide_sandbox(self, job_id: str, **kwargs):
        self.calls.append(("sandbox", kwargs))
        return snapshot(revision=self.current_revision + 1)

    def execute(self, job_id: str, *, expected_revision: int):
        if expected_revision != self.current_revision:
            raise StateStoreError("work session revision changed; refresh state")
        self.execute_side_effects += 1
        self.current_revision += 1
        self.calls.append(("execute", expected_revision))
        return snapshot(
            revision=self.current_revision,
            state=JobState.READY_TO_REVIEW.value,
        )

    def decide_review(
        self,
        job_id: str,
        *,
        action: ReviewAction,
        fingerprint: str,
        expected_revision: int,
    ):
        self.calls.append(
            ("review", (action.value, fingerprint, expected_revision))
        )
        return snapshot(revision=expected_revision + 1, state="COMPLETED")


class GatewayHarness:
    def __init__(self):
        self.service = FakeService()
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
        self.port = self.server.server_port
        self.origin = f"http://{self.host}:{self.port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, object] | str | None = None,
        headers: dict[str, str] | None = None,
    ):
        connection = http.client.HTTPConnection(
            self.host,
            self.port,
            timeout=5,
        )
        payload = None
        final_headers = dict(headers or {})
        if isinstance(body, dict):
            payload = json.dumps(body)
            final_headers.setdefault("Content-Type", "application/json")
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
        result = (
            json.loads(data.decode("utf-8"))
            if data and response.getheader("Content-Type", "").startswith(
                "application/json"
            )
            else data.decode("utf-8")
        )
        headers_out = dict(response.getheaders())
        connection.close()
        return response.status, headers_out, result

    def session_cookie(self) -> str:
        status, headers, _ = self.request("GET", "/")
        assert status == 200
        cookie = SimpleCookie()
        cookie.load(headers["Set-Cookie"])
        return f"xp_session={cookie['xp_session'].value}"

    def mutation_headers(self, cookie: str) -> dict[str, str]:
        return {
            "Origin": self.origin,
            "Cookie": cookie,
            "Content-Type": "application/json",
        }


class CP09BVisualGatewayTests(unittest.TestCase):
    def test_cli_parser_exposes_development_visual_gateway_defaults(self):
        args = build_parser().parse_args(["visual-gateway"])
        self.assertEqual(args.command, "visual-gateway")
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8765)
        self.assertEqual(args.qwen_base_url, "http://127.0.0.1:8080")
        self.assertEqual(args.qwen_model, "local")


    def test_cli_command_wires_work_session_service_into_gateway(self):
        class FakeServer:
            def __init__(self):
                self.server_address = ("127.0.0.1", 0)
                self.served = False
                self.closed = False

            def serve_forever(self):
                self.served = True

            def server_close(self):
                self.closed = True

        fake_server = FakeServer()
        with tempfile.TemporaryDirectory() as td:
            stdout = StringIO()
            with patch(
                "xp_next.cli.make_visual_gateway",
                return_value=fake_server,
            ) as make_gateway, redirect_stdout(stdout):
                code = main(
                    [
                        "--home",
                        str(Path(td) / "runtime"),
                        "visual-gateway",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "0",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertTrue(fake_server.served)
        self.assertTrue(fake_server.closed)
        kwargs = make_gateway.call_args.kwargs
        self.assertEqual(kwargs["host"], "127.0.0.1")
        self.assertEqual(kwargs["port"], 0)
        self.assertIsNone(kwargs["static_root"])
        self.assertEqual(
            type(kwargs["service"]).__name__,
            "WorkSessionService",
        )
        self.assertIn("Visual Gateway", stdout.getvalue())

    def test_non_loopback_bind_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            make_visual_gateway(
                host="0.0.0.0",
                port=0,
                service=FakeService(),
            )

    def test_get_contract_and_session_cookie(self):
        harness = GatewayHarness()
        try:
            status, headers, body = harness.request("GET", "/")
            self.assertEqual(status, 200)
            self.assertIn("xp_session=", headers["Set-Cookie"])
            self.assertIn("HttpOnly", headers["Set-Cookie"])
            self.assertIn("SameSite=Strict", headers["Set-Cookie"])

            status, _, body = harness.request("GET", "/api/v2/snapshot")
            self.assertEqual(status, 200)
            self.assertEqual(body["product"], "XP Next")

            status, _, body = harness.request("GET", "/api/v2/projects")
            self.assertEqual(status, 200)
            self.assertEqual(body["projects"][0]["id"], "p1")

            status, _, body = harness.request(
                "GET",
                "/api/v2/work-sessions/j1",
            )
            self.assertEqual(status, 200)
            self.assertEqual(body["id"], "j1")

            status, _, body = harness.request("GET", "/api/v2/nope")
            self.assertEqual(status, 404)
            self.assertFalse(body["ok"])
        finally:
            harness.close()

    def test_mutation_requires_cookie_exact_origin_and_json(self):
        harness = GatewayHarness()
        try:
            body = {"project_id": "p1"}

            status, _, _ = harness.request(
                "POST",
                "/api/v2/projects/select",
                body=body,
                headers={
                    "Origin": harness.origin,
                    "Content-Type": "application/json",
                },
            )
            self.assertEqual(status, 403)
            self.assertEqual(harness.service.calls, [])

            cookie = harness.session_cookie()
            status, _, _ = harness.request(
                "POST",
                "/api/v2/projects/select",
                body=body,
                headers={
                    "Origin": "http://evil.invalid",
                    "Cookie": cookie,
                    "Content-Type": "application/json",
                },
            )
            self.assertEqual(status, 403)
            self.assertEqual(harness.service.calls, [])

            status, _, _ = harness.request(
                "POST",
                "/api/v2/projects/select",
                body=json.dumps(body),
                headers={
                    "Origin": harness.origin,
                    "Cookie": cookie,
                    "Content-Type": "text/plain",
                },
            )
            self.assertEqual(status, 415)
            self.assertEqual(harness.service.calls, [])
        finally:
            harness.close()

    def test_post_routes_dispatch_structured_decisions(self):
        harness = GatewayHarness()
        try:
            cookie = harness.session_cookie()
            headers = harness.mutation_headers(cookie)

            status, _, body = harness.request(
                "POST",
                "/api/v2/work-sessions",
                body={
                    "job_id": "j1",
                    "project_id": "p1",
                    "goal": "goal",
                    "worker_prompt": "{}",
                    "verifier_command": "python -c 'pass'",
                },
                headers=headers,
            )
            self.assertEqual(status, 201)
            self.assertEqual(body["id"], "j1")

            status, _, _ = harness.request(
                "POST",
                "/api/v2/work-sessions/j1/worker-decision",
                body={
                    "backend_id": "lightweight_local",
                    "approved": True,
                    "expected_revision": 1,
                },
                headers=headers,
            )
            self.assertEqual(status, 200)

            status, _, _ = harness.request(
                "POST",
                "/api/v2/work-sessions/j1/sandbox-decision",
                body={
                    "approved": True,
                    "expected_revision": 2,
                },
                headers=headers,
            )
            self.assertEqual(status, 200)

            status, _, _ = harness.request(
                "POST",
                "/api/v2/work-sessions/j1/review-decision",
                body={
                    "action": "DISCARD",
                    "fingerprint": "abc",
                    "expected_revision": 4,
                },
                headers=headers,
            )
            self.assertEqual(status, 200)
            self.assertIn(
                ("review", ("DISCARD", "abc", 4)),
                harness.service.calls,
            )
        finally:
            harness.close()

    def test_duplicate_execute_with_stale_revision_returns_409_without_second_side_effect(self):
        harness = GatewayHarness()
        try:
            cookie = harness.session_cookie()
            headers = harness.mutation_headers(cookie)
            payload = {"expected_revision": 1}

            first, _, body = harness.request(
                "POST",
                "/api/v2/work-sessions/j1/execute",
                body=payload,
                headers=headers,
            )
            self.assertEqual(first, 200)
            self.assertEqual(body["revision"], 2)

            second, _, body = harness.request(
                "POST",
                "/api/v2/work-sessions/j1/execute",
                body=payload,
                headers=headers,
            )
            self.assertEqual(second, 409)
            self.assertFalse(body["ok"])
            self.assertEqual(harness.service.execute_side_effects, 1)
        finally:
            harness.close()

    def test_bad_json_is_400_and_unexpected_errors_do_not_leak_tracebacks(self):
        harness = GatewayHarness()
        try:
            cookie = harness.session_cookie()
            headers = harness.mutation_headers(cookie)
            status, _, body = harness.request(
                "POST",
                "/api/v2/projects/select",
                body="{bad",
                headers=headers,
            )
            self.assertEqual(status, 400)
            self.assertFalse(body["ok"])
        finally:
            harness.close()


if __name__ == "__main__":
    unittest.main()
