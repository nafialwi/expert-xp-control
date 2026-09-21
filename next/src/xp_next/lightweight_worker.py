from __future__ import annotations

import json
from pathlib import Path

from .worker_contract import (
    WorkerReadiness,
    WorkerRequest,
    WorkerResult,
    WorkerStatus,
)


_MAX_FILE_BYTES = 1024 * 1024
_SENSITIVE_NAMES = {
    ".env",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".git-credentials",
    "auth.json",
    "credentials",
    "credentials.json",
}


class LightweightWorkerError(ValueError):
    pass


def _is_sensitive_name(name: str) -> bool:
    return name in _SENSITIVE_NAMES or name.startswith(".env.")


def _safe_relative_path(raw: object) -> Path:
    if not isinstance(raw, str):
        raise LightweightWorkerError("path must be a string")
    value = raw.strip()
    if not value:
        raise LightweightWorkerError("path must not be empty")

    relative = Path(value)
    if relative.is_absolute():
        raise LightweightWorkerError("absolute paths are forbidden")
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise LightweightWorkerError("path traversal is forbidden")
    if ".git" in relative.parts:
        raise LightweightWorkerError(".git mutation is forbidden")
    if _is_sensitive_name(relative.name):
        raise LightweightWorkerError("sensitive-file mutation is forbidden")
    return relative


def _safe_target(cwd: Path, relative: Path) -> Path:
    current = cwd
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise LightweightWorkerError("symlink parent is forbidden")
        if not current.exists():
            raise LightweightWorkerError("parent directory must already exist")
        if not current.is_dir():
            raise LightweightWorkerError("path parent is not a directory")

    target = cwd / relative
    if target.is_symlink():
        raise LightweightWorkerError("symlink target is forbidden")

    resolved_parent = target.parent.resolve(strict=True)
    try:
        resolved_parent.relative_to(cwd)
    except ValueError as exc:
        raise LightweightWorkerError("target escapes isolated cwd") from exc
    return target


def _bounded_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise LightweightWorkerError(f"{label} must be a string")
    encoded = value.encode("utf-8")
    if len(encoded) > _MAX_FILE_BYTES:
        raise LightweightWorkerError(f"{label} exceeds lightweight worker size limit")
    return value



def validate_lightweight_operation_prompt(prompt: str) -> tuple[bool, str]:
    """Validate only the explicit operation shape; no filesystem state is read."""
    try:
        payload = json.loads(prompt)
    except json.JSONDecodeError:
        return False, "lightweight operation must be an explicit JSON object"
    if not isinstance(payload, dict):
        return False, "lightweight operation payload must be a JSON object"

    operation = payload.get("operation")
    if operation == "replace_text":
        allowed_keys = {"operation", "path", "expected_text", "new_text"}
        required_keys = allowed_keys
    elif operation == "create_text":
        allowed_keys = {"operation", "path", "new_text"}
        required_keys = allowed_keys
    else:
        return False, "unsupported lightweight operation"

    missing = required_keys - set(payload)
    if missing:
        return False, f"missing lightweight fields: {', '.join(sorted(missing))}"
    unknown = set(payload) - allowed_keys
    if unknown:
        return False, f"unknown lightweight fields: {', '.join(sorted(unknown))}"

    try:
        _safe_relative_path(payload.get("path"))
        _bounded_text(payload.get("new_text"), "new_text")
        if operation == "replace_text":
            _bounded_text(payload.get("expected_text"), "expected_text")
    except LightweightWorkerError as exc:
        return False, str(exc)

    return True, str(operation)


class LightweightLocalWorker:
    """Deterministic sandbox-only file worker for explicit bounded operations."""

    backend_id = "lightweight_local"

    def readiness(self) -> WorkerReadiness:
        return WorkerReadiness(
            ready=True,
            status="READY",
            detail="deterministic local file worker is available",
            backend_id=self.backend_id,
            model_transport="none",
            containment="isolated_workspace_direct_file_io",
        )

    @staticmethod
    def _parse_operation(prompt: str) -> dict[str, object]:
        try:
            payload = json.loads(prompt)
        except json.JSONDecodeError as exc:
            raise LightweightWorkerError(
                "lightweight worker requires one explicit JSON operation"
            ) from exc
        if not isinstance(payload, dict):
            raise LightweightWorkerError("operation payload must be a JSON object")
        return payload

    def run(
        self,
        request: WorkerRequest,
        *,
        home: Path | None = None,
        tmp: Path | None = None,
    ) -> WorkerResult:
        del home, tmp
        readiness = self.readiness()
        try:
            payload = self._parse_operation(request.prompt)
            operation = payload.get("operation")
            allowed_keys: set[str]

            if operation == "replace_text":
                allowed_keys = {"operation", "path", "expected_text", "new_text"}
            elif operation == "create_text":
                allowed_keys = {"operation", "path", "new_text"}
            else:
                raise LightweightWorkerError(
                    "unsupported operation; expected replace_text or create_text"
                )

            unknown = set(payload) - allowed_keys
            if unknown:
                raise LightweightWorkerError(
                    f"unknown operation fields: {', '.join(sorted(unknown))}"
                )

            relative = _safe_relative_path(payload.get("path"))
            target = _safe_target(request.cwd, relative)
            new_text = _bounded_text(payload.get("new_text"), "new_text")

            if operation == "replace_text":
                expected_text = _bounded_text(
                    payload.get("expected_text"),
                    "expected_text",
                )
                if not target.exists() or not target.is_file():
                    raise LightweightWorkerError(
                        "replace_text target must be an existing regular file"
                    )
                if target.stat().st_size > _MAX_FILE_BYTES:
                    raise LightweightWorkerError(
                        "replace_text target exceeds lightweight worker size limit"
                    )
                current = target.read_text(encoding="utf-8")
                if current != expected_text:
                    raise LightweightWorkerError(
                        "replace_text expected_text does not match current file"
                    )
                if current == new_text:
                    raise LightweightWorkerError(
                        "replace_text would not change the file"
                    )
                target.write_text(new_text, encoding="utf-8")

            elif operation == "create_text":
                if target.exists():
                    raise LightweightWorkerError(
                        "create_text target must not already exist"
                    )
                target.write_text(new_text, encoding="utf-8")

            return WorkerResult(
                status=WorkerStatus.COMPLETED,
                output=f"{operation}:{relative.as_posix()}",
                returncode=0,
                backend_id=self.backend_id,
                model_transport=readiness.model_transport,
                containment=readiness.containment,
                apply_to_original_performed=False,
                detail="bounded sandbox file operation completed",
            )
        except Exception as exc:
            return WorkerResult(
                status=WorkerStatus.NEEDS_ATTENTION,
                output="",
                returncode=1,
                backend_id=self.backend_id,
                model_transport=readiness.model_transport,
                containment=readiness.containment,
                apply_to_original_performed=False,
                detail=f"{type(exc).__name__}: {exc}"[:500],
            )
