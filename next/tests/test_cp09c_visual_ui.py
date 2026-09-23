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

from xp_next.cli import _default_visual_static_root, main
from xp_next.visual_gateway import make_visual_gateway


class FakeVisualService:
    def __init__(self):
        self.activity_calls: list[tuple[str | None, int]] = []

    def visual_snapshot(self):
        return {"product": "XP Next", "active_project": None}

    def list_visual_projects(self):
        return []

    def public_activity(self, job_id=None, *, limit=50):
        self.activity_calls.append((job_id, limit))
        return [
            {
                "action": "verify",
                "status": "Selesai",
                "summary": "Verification PASS",
                "source": "verifier",
                "processor": "local",
                "live": False,
                "created_at": "2026-09-23T00:00:00Z",
            }
        ]


class GatewayHarness:
    def __init__(self, *, static_root: Path | None = None):
        self.service = FakeVisualService()
        self.server = make_visual_gateway(
            host="127.0.0.1",
            port=0,
            service=self.service,
            static_root=static_root,
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()
        self.host = "127.0.0.1"
        self.port = int(self.server.server_port)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def get(self, path: str):
        connection = http.client.HTTPConnection(
            self.host,
            self.port,
            timeout=5,
        )
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        content_type = response.getheader("Content-Type", "")
        parsed = (
            json.loads(body.decode("utf-8"))
            if content_type.startswith("application/json")
            else body.decode("utf-8")
        )
        headers = dict(response.getheaders())
        status = response.status
        connection.close()
        return status, headers, parsed


class CP09CVisualGatewayTests(unittest.TestCase):
    def test_default_visual_static_root_points_to_canonical_pwa(self):
        root = _default_visual_static_root()
        self.assertIsInstance(root, Path)
        assert isinstance(root, Path)
        self.assertTrue(root.is_dir())
        self.assertEqual(root.name, "xp_visual")
        self.assertTrue((root / "index.html").is_file())
        self.assertTrue((root / "app.js").is_file())
        self.assertTrue((root / "styles.css").is_file())

    def test_visual_gateway_cli_uses_canonical_static_root_by_default(self):
        class FakeServer:
            def __init__(self):
                self.server_address = ("127.0.0.1", 8765)
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
                        "8765",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertTrue(fake_server.served)
        self.assertTrue(fake_server.closed)
        static_root = make_gateway.call_args.kwargs["static_root"]
        self.assertEqual(static_root, _default_visual_static_root())

    def test_gateway_serves_canonical_index_when_static_root_is_set(self):
        root = _default_visual_static_root()
        harness = GatewayHarness(static_root=root)
        try:
            status, headers, body = harness.get("/")
            self.assertEqual(status, 200)
            self.assertIn("text/html", headers["Content-Type"])
            self.assertIn("Expert XP", body)
            self.assertIn("xp_session=", headers["Set-Cookie"])
        finally:
            harness.close()

    def test_activity_endpoint_delegates_bounded_query(self):
        harness = GatewayHarness()
        try:
            status, _, body = harness.get(
                "/api/v2/activity?job_id=work-123&limit=7"
            )
            self.assertEqual(status, 200)
            self.assertEqual(body["activities"][0]["action"], "verify")
            self.assertEqual(
                harness.service.activity_calls,
                [("work-123", 7)],
            )
        finally:
            harness.close()

    def test_activity_endpoint_rejects_invalid_limit(self):
        harness = GatewayHarness()
        try:
            status, _, body = harness.get("/api/v2/activity?limit=0")
            self.assertEqual(status, 400)
            self.assertFalse(body["ok"])
            self.assertEqual(harness.service.activity_calls, [])
        finally:
            harness.close()


if __name__ == "__main__":
    unittest.main()
