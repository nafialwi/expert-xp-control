from __future__ import annotations

import unittest
from datetime import datetime, timezone

from xp.ai.agents.live_readiness import (
    LiveHTTPResult,
    LiveReadinessPermissionError,
    LiveReadinessProbe,
    build_live_readiness_probe,
)
from xp.ai.agents.local_backends import LOCAL_QWEN, ROUTER_9


FIXED_TIME = datetime(2026, 9, 18, 8, 30, 0, tzinfo=timezone.utc)


class AF05LiveReadinessTests(unittest.TestCase):
    def test_live_check_requires_explicit_permission_before_http(self):
        calls = []

        def fake_get(url, timeout):
            calls.append((url, timeout))
            return LiveHTTPResult(200, "ok")

        with self.assertRaisesRegex(
            LiveReadinessPermissionError,
            "explicit allow_live=True",
        ):
            build_live_readiness_probe(
                backend=LOCAL_QWEN,
                allow_live=False,
                http_get=fake_get,
                clock=lambda: FIXED_TIME,
            )

        self.assertEqual(calls, [])

    def test_qwen_live_readiness_calls_exact_endpoint_once(self):
        calls = []

        def fake_get(url, timeout):
            calls.append((url, timeout))
            return LiveHTTPResult(200, "health ok")

        probe = build_live_readiness_probe(
            backend=LOCAL_QWEN,
            allow_live=True,
            http_get=fake_get,
            clock=lambda: FIXED_TIME,
            timeout_seconds=1.5,
        )

        result = probe()

        self.assertTrue(result.ready)
        self.assertEqual(result.status, "READY")
        self.assertIn("LIVE local-qwen", result.detail)
        self.assertEqual(
            calls,
            [(LOCAL_QWEN.readiness_url, 1.5)],
        )
        self.assertEqual(result.metadata["source"], "LIVE")
        self.assertEqual(result.metadata["backend_id"], "local-qwen")
        self.assertEqual(
            result.metadata["checked_at"],
            FIXED_TIME.isoformat(),
        )
        self.assertEqual(result.metadata["status_code"], "200")

    def test_9router_live_readiness_does_not_call_qwen(self):
        calls = []

        def fake_get(url, timeout):
            calls.append((url, timeout))
            return LiveHTTPResult(200, "models ok")

        probe = build_live_readiness_probe(
            backend=ROUTER_9,
            allow_live=True,
            http_get=fake_get,
            clock=lambda: FIXED_TIME,
        )

        result = probe()

        self.assertTrue(result.ready)
        self.assertEqual(calls, [(ROUTER_9.readiness_url, 2.5)])
        self.assertNotEqual(
            ROUTER_9.readiness_url,
            LOCAL_QWEN.readiness_url,
        )
        self.assertEqual(result.metadata["backend_id"], "9router")

    def test_unavailable_backend_surfaces_perlu_perhatian(self):
        probe = build_live_readiness_probe(
            backend=LOCAL_QWEN,
            allow_live=True,
            http_get=lambda url, timeout: LiveHTTPResult(
                0,
                "connection refused",
            ),
            clock=lambda: FIXED_TIME,
        )

        result = probe()

        self.assertFalse(result.ready)
        self.assertEqual(result.status, "PERLU_PERHATIAN")
        self.assertIn("connection refused", result.detail)
        self.assertEqual(result.metadata["source"], "LIVE")

    def test_http_error_surfaces_perlu_perhatian_without_fallback(self):
        calls = []

        def fake_get(url, timeout):
            calls.append(url)
            return LiveHTTPResult(503, "HTTP 503")

        probe = build_live_readiness_probe(
            backend=LOCAL_QWEN,
            allow_live=True,
            http_get=fake_get,
            clock=lambda: FIXED_TIME,
        )

        result = probe()

        self.assertFalse(result.ready)
        self.assertEqual(result.status, "PERLU_PERHATIAN")
        self.assertEqual(calls, [LOCAL_QWEN.readiness_url])

    def test_no_cache_or_auto_refresh_each_explicit_call_is_observable(self):
        calls = []

        def fake_get(url, timeout):
            calls.append(url)
            return LiveHTTPResult(200, "ok")

        probe = LiveReadinessProbe(
            backend=LOCAL_QWEN,
            allow_live=True,
            http_get=fake_get,
            clock=lambda: FIXED_TIME,
        )

        first = probe()
        second = probe()

        self.assertEqual(len(calls), 2)
        self.assertEqual(first.metadata["source"], "LIVE")
        self.assertEqual(second.metadata["source"], "LIVE")


if __name__ == "__main__":
    unittest.main()
