from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .reasoning import (
    ReasoningRequest,
    ReasoningResult,
    ReasoningStatus,
    verify_reasoning_result,
)


class LocalQwenConfigError(ValueError):
    pass


@dataclass(frozen=True)
class LocalQwenReadiness:
    ready: bool
    status: str
    detail: str
    backend_id: str = "local_qwen"
    transport: str = "loopback_http"
    external_network_used: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "status": self.status,
            "detail": self.detail,
            "backend_id": self.backend_id,
            "transport": self.transport,
            "external_network_used": self.external_network_used,
        }


RequestJSON = Callable[[str, str, dict[str, object] | None, float], dict[str, object]]


def _default_request_json(
    method: str,
    url: str,
    payload: dict[str, object] | None,
    timeout: float,
) -> dict[str, object]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, method=method, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        body = response.read(1_000_000).decode("utf-8", "replace")
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise RuntimeError("local Qwen returned a non-object JSON response")
    return parsed


def _validate_loopback_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme != "http":
        raise LocalQwenConfigError("local Qwen must use http loopback")
    if parsed.hostname not in {"127.0.0.1", "::1"}:
        raise LocalQwenConfigError("local Qwen host must be loopback")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise LocalQwenConfigError("local Qwen URL must not contain credentials/query/fragment")
    if parsed.path not in {"", "/"}:
        raise LocalQwenConfigError("local Qwen base URL must not contain a path")
    return base_url.rstrip("/")


class LocalQwenAdapter:
    """Explicit read-only reasoning adapter for a loopback llama-server."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8080",
        model: str = "local",
        timeout: float = 120.0,
        request_json: RequestJSON = _default_request_json,
    ):
        if not model.strip():
            raise LocalQwenConfigError("model must not be empty")
        if timeout <= 0:
            raise LocalQwenConfigError("timeout must be positive")
        self.base_url = _validate_loopback_base_url(base_url)
        self.model = model.strip()
        self.timeout = timeout
        self._request_json = request_json

    def readiness(self) -> LocalQwenReadiness:
        try:
            payload = self._request_json(
                "GET",
                f"{self.base_url}/health",
                None,
                min(self.timeout, 5.0),
            )
        except Exception as exc:
            return LocalQwenReadiness(
                ready=False,
                status="NEEDS_ATTENTION",
                detail=f"{type(exc).__name__}: {exc}"[:500],
            )

        status = str(payload.get("status", "")).lower()
        if status == "ok":
            return LocalQwenReadiness(
                ready=True,
                status="READY",
                detail="loopback llama-server health is ok",
            )
        return LocalQwenReadiness(
            ready=False,
            status="NEEDS_ATTENTION",
            detail=f"unexpected health status: {payload.get('status')!r}"[:500],
        )

    @staticmethod
    def _prompt(request: ReasoningRequest) -> str:
        context_json = json.dumps(
            request.context,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return (
            "USER_GOAL:\n"
            f"{request.task.goal}\n\n"
            "BOUNDED_PROJECT_CONTEXT_JSON:\n"
            f"{context_json}\n\n"
            "Return 1-3 concise plain-text sentences supported by the supplied context. "
            "Do not return JSON, code, or repeated filler tokens. "
            "Do not expose hidden chain-of-thought. "
            "Do not claim to have modified files or used external network access."
        )

    def reason(self, request: ReasoningRequest) -> ReasoningResult:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are XP Next's local read-only reasoning backend. "
                        "Use only the supplied bounded project context. "
                        "No tool use, file mutation, or external network access is allowed."
                    ),
                },
                {
                    "role": "user",
                    "content": self._prompt(request),
                },
            ],
            "max_tokens": request.max_tokens,
            "temperature": 0.1,
            "stream": False,
        }

        try:
            response = self._request_json(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                payload,
                self.timeout,
            )
            choices = response.get("choices")
            if not isinstance(choices, list) or not choices:
                raise RuntimeError("local Qwen response has no choices")
            message = choices[0].get("message")
            if not isinstance(message, dict):
                raise RuntimeError("local Qwen response has no message")
            output = str(message.get("content", "")).strip()
            model = str(response.get("model") or self.model)
            result = ReasoningResult(
                status=ReasoningStatus.COMPLETED,
                output=output,
                backend_id="local_qwen",
                model=model,
                transport="loopback_http",
                external_network_used=False,
            )
            ok, detail = verify_reasoning_result(result)
            if not ok:
                return ReasoningResult(
                    status=ReasoningStatus.NEEDS_ATTENTION,
                    output="",
                    backend_id="local_qwen",
                    model=model,
                    transport="loopback_http",
                    external_network_used=False,
                    detail=detail,
                )
            return result
        except Exception as exc:
            return ReasoningResult(
                status=ReasoningStatus.NEEDS_ATTENTION,
                output="",
                backend_id="local_qwen",
                model=self.model,
                transport="loopback_http",
                external_network_used=False,
                detail=f"{type(exc).__name__}: {exc}"[:500],
            )
