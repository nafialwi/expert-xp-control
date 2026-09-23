from __future__ import annotations

from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import secrets
import threading
from typing import Any
from urllib.parse import unquote, urlparse

from .state_store import JobNotFound, ProjectNotFound, StateStoreError
from .work_flow import WorkFlowNeedsAttention
from .work_session import WorkSessionSnapshot, public_session
from .zero_cost_e2e import ReviewAction


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_MAX_BODY_BYTES = 64 * 1024


def _validate_bind_host(host: str) -> None:
    if host not in _LOOPBACK_HOSTS:
        raise ValueError("visual gateway must bind to loopback only")


def _display_host(host: str) -> str:
    return f"[{host}]" if ":" in host else host


def _header_host(value: str) -> str:
    raw = value.strip()
    if raw.startswith("["):
        end = raw.find("]")
        return raw[1:end] if end > 0 else ""
    return raw.split(":", 1)[0]


def _public_result(value: object) -> object:
    if isinstance(value, WorkSessionSnapshot):
        return public_session(value)
    return value


class XPVisualGateway(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        *,
        service: object,
        static_root: Path | None,
        bind_host: str,
    ):
        self.service = service
        self.static_root = static_root
        self.bind_host = bind_host
        self.session_nonce = secrets.token_urlsafe(32)
        self.service_lock = threading.RLock()
        super().__init__(address, handler)

    @property
    def origin(self) -> str:
        return (
            f"http://{_display_host(self.bind_host)}:"
            f"{int(self.server_address[1])}"
        )


class _GatewayHandler(BaseHTTPRequestHandler):
    server: XPVisualGateway

    def log_message(self, format: str, *args: object) -> None:
        return

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")

    def _send_json(
        self,
        status: int,
        payload: dict[str, object] | list[object],
    ) -> None:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_html(
        self,
        status: int,
        body: bytes,
        *,
        content_type: str = "text/html; charset=utf-8",
        set_session: bool = False,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; "
            "style-src 'self'; script-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'",
        )
        if set_session:
            self.send_header(
                "Set-Cookie",
                (
                    f"xp_session={self.server.session_nonce}; "
                    "HttpOnly; SameSite=Strict; Path=/"
                ),
            )
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _loopback_host_header_ok(self) -> bool:
        host = _header_host(self.headers.get("Host", ""))
        return host in _LOOPBACK_HOSTS

    def _session_cookie_ok(self) -> bool:
        raw = self.headers.get("Cookie", "")
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return False
        morsel = cookie.get("xp_session")
        return (
            morsel is not None
            and secrets.compare_digest(
                morsel.value,
                self.server.session_nonce,
            )
        )

    def _mutation_preflight(self) -> bool:
        if not self._loopback_host_header_ok():
            self._send_json(
                403,
                {"ok": False, "error": "loopback host required"},
            )
            return False
        if self.headers.get("Origin") != self.server.origin:
            self._send_json(
                403,
                {"ok": False, "error": "same-origin request required"},
            )
            return False
        if not self._session_cookie_ok():
            self._send_json(
                403,
                {"ok": False, "error": "valid local session required"},
            )
            return False
        content_type = self.headers.get("Content-Type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            self._send_json(
                415,
                {"ok": False, "error": "application/json required"},
            )
            return False
        return True

    def _read_json(self) -> dict[str, object]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValueError("Content-Length is required")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length < 0 or length > _MAX_BODY_BYTES:
            raise ValueError("request body exceeds bounded size")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON body") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _serve_root(self) -> None:
        static_root = self.server.static_root
        if static_root is not None:
            index = static_root / "index.html"
            if index.is_file():
                self._send_html(
                    200,
                    index.read_bytes(),
                    set_session=True,
                )
                return
        body = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Expert XP</title></head><body>"
            "<main><h1>Expert XP</h1>"
            "<p>Local visual gateway is ready.</p></main>"
            "</body></html>"
        ).encode("utf-8")
        self._send_html(200, body, set_session=True)

    def _serve_static(self, request_path: str) -> bool:
        root = self.server.static_root
        if root is None:
            return False
        relative = unquote(request_path.lstrip("/"))
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return False
        if not candidate.is_file():
            return False
        content_type = (
            mimetypes.guess_type(candidate.name)[0]
            or "application/octet-stream"
        )
        self._send_html(
            200,
            candidate.read_bytes(),
            content_type=content_type,
        )
        return True

    def _api_get(self, path: str) -> bool:
        service = self.server.service
        if path == "/api/v2/snapshot":
            self._send_json(
                200,
                dict(service.visual_snapshot()),
            )
            return True
        if path == "/api/v2/projects":
            self._send_json(
                200,
                {"projects": list(service.list_visual_projects())},
            )
            return True
        prefix = "/api/v2/work-sessions/"
        if path.startswith(prefix):
            job_id = path[len(prefix):]
            if not job_id or "/" in job_id:
                return False
            result = _public_result(service.get(job_id))
            if not isinstance(result, dict):
                raise TypeError("session projection must be an object")
            self._send_json(200, result)
            return True
        return False

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/":
                self._serve_root()
                return
            if path.startswith("/api/"):
                with self.server.service_lock:
                    handled = self._api_get(path)
                if handled:
                    return
                self._send_json(
                    404,
                    {"ok": False, "error": "route not found"},
                )
                return
            if self._serve_static(path):
                return
            self._send_json(
                404,
                {"ok": False, "error": "route not found"},
            )
        except (JobNotFound, ProjectNotFound):
            self._send_json(404, {"ok": False, "error": "not found"})
        except StateStoreError as exc:
            status = 404 if "not found" in str(exc).lower() else 409
            self._send_json(
                status,
                {"ok": False, "error": str(exc)[:300]},
            )
        except Exception:
            self._send_json(
                500,
                {"ok": False, "error": "internal gateway error"},
            )

    def _dispatch_post(
        self,
        path: str,
        payload: dict[str, object],
    ) -> tuple[int, object]:
        service = self.server.service

        if path == "/api/v2/projects/select":
            project_id = str(payload.get("project_id") or "").strip()
            if not project_id:
                raise ValueError("project_id is required")
            return 200, service.select_visual_project(project_id)

        if path == "/api/v2/work-sessions":
            job_id = str(payload.get("job_id") or "").strip()
            goal = str(payload.get("goal") or "").strip()
            if not job_id or not goal:
                raise ValueError("job_id and goal are required")
            project_value = payload.get("project_id")
            result = service.create(
                job_id=job_id,
                project_id=(
                    None
                    if project_value is None
                    else str(project_value)
                ),
                goal=goal,
                worker_prompt=(
                    None
                    if payload.get("worker_prompt") is None
                    else str(payload.get("worker_prompt"))
                ),
                verifier_command=(
                    None
                    if payload.get("verifier_command") is None
                    else str(payload.get("verifier_command"))
                ),
                verifier_timeout=float(
                    payload.get("verifier_timeout", 120.0)
                ),
                requested_backend=(
                    None
                    if payload.get("requested_backend") is None
                    else str(payload.get("requested_backend"))
                ),
            )
            return 201, _public_result(result)

        prefix = "/api/v2/work-sessions/"
        if not path.startswith(prefix):
            raise LookupError("route not found")
        suffix = path[len(prefix):]
        if "/" not in suffix:
            raise LookupError("route not found")
        job_id, action_path = suffix.split("/", 1)
        if not job_id:
            raise LookupError("route not found")
        expected_revision = int(payload.get("expected_revision"))

        if action_path == "worker-decision":
            backend_id = str(payload.get("backend_id") or "").strip()
            if not backend_id or not isinstance(
                payload.get("approved"),
                bool,
            ):
                raise ValueError(
                    "backend_id and boolean approved are required"
                )
            return 200, _public_result(
                service.decide_worker(
                    job_id,
                    backend_id=backend_id,
                    approved=bool(payload["approved"]),
                    expected_revision=expected_revision,
                )
            )

        if action_path == "sandbox-decision":
            if not isinstance(payload.get("approved"), bool):
                raise ValueError("boolean approved is required")
            return 200, _public_result(
                service.decide_sandbox(
                    job_id,
                    approved=bool(payload["approved"]),
                    expected_revision=expected_revision,
                )
            )

        if action_path == "execute":
            return 200, _public_result(
                service.execute(
                    job_id,
                    expected_revision=expected_revision,
                )
            )

        if action_path == "review-decision":
            action_raw = str(payload.get("action") or "").strip()
            fingerprint = str(
                payload.get("fingerprint") or ""
            ).strip()
            if not action_raw or not fingerprint:
                raise ValueError("action and fingerprint are required")
            action = ReviewAction(action_raw)
            return 200, _public_result(
                service.decide_review(
                    job_id,
                    action=action,
                    fingerprint=fingerprint,
                    expected_revision=expected_revision,
                )
            )

        raise LookupError("route not found")

    def do_POST(self) -> None:
        if not self._mutation_preflight():
            return
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            with self.server.service_lock:
                status, result = self._dispatch_post(
                    parsed.path,
                    payload,
                )
            if isinstance(result, dict):
                body = result
            else:
                body = {"result": result}
            self._send_json(status, body)
        except LookupError:
            self._send_json(
                404,
                {"ok": False, "error": "route not found"},
            )
        except (JobNotFound, ProjectNotFound):
            self._send_json(404, {"ok": False, "error": "not found"})
        except StateStoreError as exc:
            status = 404 if "not found" in str(exc).lower() else 409
            self._send_json(
                status,
                {"ok": False, "error": str(exc)[:300]},
            )
        except WorkFlowNeedsAttention as exc:
            self._send_json(
                409,
                {"ok": False, "error": str(exc)[:300]},
            )
        except (TypeError, ValueError):
            self._send_json(
                400,
                {"ok": False, "error": "invalid request"},
            )
        except Exception:
            self._send_json(
                500,
                {"ok": False, "error": "internal gateway error"},
            )


def make_visual_gateway(
    *,
    host: str,
    port: int,
    service: object,
    static_root: Path | str | None = None,
) -> ThreadingHTTPServer:
    _validate_bind_host(host)
    root: Path | None = None
    if static_root is not None:
        root = Path(static_root).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("static_root must be a directory")
    return XPVisualGateway(
        (host, port),
        _GatewayHandler,
        service=service,
        static_root=root,
        bind_host=host,
    )
