from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .base import AgentReadiness
from .local_backends import LocalBackendBinding


class LiveReadinessPermissionError(PermissionError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise HTTPError(
            req.full_url,
            code,
            "redirect blocked for loopback live readiness",
            headers,
            fp,
        )


@dataclass(frozen=True)
class LiveHTTPResult:
    status_code: int
    detail: str = ""


HTTPGet = Callable[[str, float], LiveHTTPResult]
Clock = Callable[[], datetime]


def _validate_loopback_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "http":
        raise ValueError("live readiness URL must use http")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("live readiness URL must use loopback host")


def urllib_loopback_get(url: str, timeout_seconds: float) -> LiveHTTPResult:
    _validate_loopback_url(url)
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    opener = build_opener(_NoRedirect())
    req = Request(
        url,
        method="GET",
        headers={"User-Agent": "XP-AF05-LiveReadiness/1.0"},
    )
    try:
        with opener.open(req, timeout=timeout_seconds) as response:
            final_url = response.geturl()
            _validate_loopback_url(final_url)
            return LiveHTTPResult(
                status_code=int(response.status),
                detail="loopback readiness responded",
            )
    except HTTPError as exc:
        return LiveHTTPResult(
            status_code=int(exc.code),
            detail=f"HTTP {exc.code}",
        )
    except URLError as exc:
        return LiveHTTPResult(
            status_code=0,
            detail=f"unavailable: {exc.reason}",
        )
    except OSError as exc:
        return LiveHTTPResult(
            status_code=0,
            detail=f"unavailable: {exc}",
        )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LiveReadinessProbe:
    def __init__(
        self,
        *,
        backend: LocalBackendBinding,
        allow_live: bool,
        http_get: HTTPGet = urllib_loopback_get,
        clock: Clock = utc_now,
        timeout_seconds: float = 2.5,
    ) -> None:
        if not isinstance(backend, LocalBackendBinding):
            raise TypeError("backend must be LocalBackendBinding")
        if allow_live is not True:
            raise LiveReadinessPermissionError(
                "live readiness requires explicit allow_live=True"
            )
        if not callable(http_get):
            raise TypeError("http_get must be callable")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        _validate_loopback_url(backend.readiness_url)

        self._backend = backend
        self._http_get = http_get
        self._clock = clock
        self._timeout_seconds = float(timeout_seconds)

    @property
    def backend(self) -> LocalBackendBinding:
        return self._backend

    def __call__(self) -> AgentReadiness:
        checked_at = self._clock()
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)

        result = self._http_get(
            self._backend.readiness_url,
            self._timeout_seconds,
        )

        if not isinstance(result, LiveHTTPResult):
            raise TypeError("http_get must return LiveHTTPResult")

        ready = 200 <= result.status_code < 300
        status = "READY" if ready else "PERLU_PERHATIAN"
        detail = (
            f"LIVE {self._backend.backend_id}: "
            f"{result.detail or 'readiness check completed'}"
        )

        return AgentReadiness(
            ready=ready,
            status=status,
            detail=detail,
            metadata={
                "source": "LIVE",
                "backend_id": self._backend.backend_id,
                "checked_at": checked_at.isoformat(),
                "status_code": str(result.status_code),
                "readiness_url": self._backend.readiness_url,
            },
        )


def build_live_readiness_probe(
    *,
    backend: LocalBackendBinding,
    allow_live: bool,
    http_get: HTTPGet = urllib_loopback_get,
    clock: Clock = utc_now,
    timeout_seconds: float = 2.5,
) -> LiveReadinessProbe:
    return LiveReadinessProbe(
        backend=backend,
        allow_live=allow_live,
        http_get=http_get,
        clock=clock,
        timeout_seconds=timeout_seconds,
    )


__all__ = [
    "LiveHTTPResult",
    "LiveReadinessPermissionError",
    "LiveReadinessProbe",
    "build_live_readiness_probe",
    "urllib_loopback_get",
    "utc_now",
]
