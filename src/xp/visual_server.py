from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from xp.visual_workstation import SnapshotStore


ALLOWED_STATIC = {
    "/": "index.html",
    "/index.html": "index.html",
    "/styles.css": "styles.css",
    "/app.js": "app.js",
    "/manifest.webmanifest": "manifest.webmanifest",
    "/sw.js": "sw.js",
}


def make_server(
    *,
    host: str,
    port: int,
    static_root: Path,
    state_path: Path,
) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("visual workstation must bind to loopback only")

    static_root = Path(static_root).resolve()
    store = SnapshotStore(Path(state_path))

    class Handler(BaseHTTPRequestHandler):
        server_version = "XPVisual/1.0"

        def log_message(self, format, *args):
            return

        def _send_bytes(
            self,
            body: bytes,
            *,
            content_type: str,
            status: int = 200,
            cache: str = "no-store",
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self'; "
                "img-src 'self' data:; "
                "connect-src 'self'; "
                "object-src 'none'; "
                "base-uri 'none'; "
                "frame-ancestors 'none'"
            ))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/api/status":
                body = json.dumps(
                    store.read().to_dict(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                self._send_bytes(
                    body,
                    content_type="application/json; charset=utf-8",
                )
                return

            rel = ALLOWED_STATIC.get(path)
            if rel is None:
                self._send_bytes(
                    b"Not Found",
                    content_type="text/plain; charset=utf-8",
                    status=HTTPStatus.NOT_FOUND,
                )
                return

            target = static_root / rel
            if not target.is_file():
                self._send_bytes(
                    b"Not Found",
                    content_type="text/plain; charset=utf-8",
                    status=HTTPStatus.NOT_FOUND,
                )
                return

            mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if target.name == "manifest.webmanifest":
                mime = "application/manifest+json"
            elif target.name == "sw.js":
                mime = "application/javascript"
            self._send_bytes(
                target.read_bytes(),
                content_type=mime,
                cache=(
                    "no-cache"
                    if target.name in {"index.html", "sw.js"}
                    else "public, max-age=300"
                ),
            )

    return ThreadingHTTPServer((host, port), Handler)


__all__ = ["make_server"]
