from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .recovery_manifest import RecoveryManifestV1

BUNDLE_SCHEMA_VERSION = 1
MANIFEST_MEMBER = "recovery-manifest.json"
INDEX_MEMBER = "bundle-index.json"
PAYLOAD_PREFIX = "payload/"

_SECRET_PATTERNS = (
    re.compile(
        rb"(?i)(api[_-]?key|token|password|passwd|authorization)"
        rb"\s*[:=]\s*[\"']?[A-Za-z0-9._\-]{24,}"
    ),
    re.compile(rb"(?i)bearer\s+[A-Za-z0-9._\-]{24,}"),
    re.compile(rb"\bsk-[A-Za-z0-9]{24,}\b"),
)

_TEXT_SCAN_LIMIT = 2 * 1024 * 1024
_MAX_FILE_BYTES = 16 * 1024 * 1024


class RecoveryBundleError(ValueError):
    pass


@dataclass(frozen=True)
class RecoveryBundleMember:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class RecoveryBundleExport:
    bundle_path: Path
    members: tuple[RecoveryBundleMember, ...]
    manifest_sha256: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _portable_rel_path(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecoveryBundleError("bundle path must be non-empty")
    value = value.strip()
    if "\\" in value:
        raise RecoveryBundleError("bundle path must use POSIX separators")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise RecoveryBundleError("bundle path must be relative")

    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RecoveryBundleError(
            "bundle path must not contain traversal or dot segments"
        )
    return path.as_posix()


def _read_payload_file(project_root: Path, rel_path: str) -> bytes:
    rel_path = _portable_rel_path(rel_path)
    root = project_root.resolve()
    path = project_root.joinpath(*PurePosixPath(rel_path).parts)

    if path.is_symlink():
        raise RecoveryBundleError(
            f"symlink payload is forbidden: {rel_path}"
        )
    if not path.exists():
        raise RecoveryBundleError(
            f"required payload file is missing: {rel_path}"
        )
    if not path.is_file():
        raise RecoveryBundleError(
            f"required payload path is not a file: {rel_path}"
        )

    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RecoveryBundleError(
            f"payload escapes project root: {rel_path}"
        ) from exc

    size = resolved.stat().st_size
    if size > _MAX_FILE_BYTES:
        raise RecoveryBundleError(
            f"payload exceeds size limit: {rel_path}"
        )

    data = resolved.read_bytes()
    if len(data) <= _TEXT_SCAN_LIMIT:
        for pattern in _SECRET_PATTERNS:
            if pattern.search(data):
                raise RecoveryBundleError(
                    f"secret-like content detected: {rel_path}"
                )
    return data


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def export_recovery_bundle(
    *,
    manifest: RecoveryManifestV1,
    project_root: Path,
    destination: Path,
) -> RecoveryBundleExport:
    if not isinstance(manifest, RecoveryManifestV1):
        raise TypeError("manifest must be RecoveryManifestV1")
    if not isinstance(project_root, Path):
        raise TypeError("project_root must be pathlib.Path")
    if not isinstance(destination, Path):
        raise TypeError("destination must be pathlib.Path")

    if not project_root.exists() or not project_root.is_dir():
        raise RecoveryBundleError(
            "project_root must be an existing directory"
        )

    destination_parent = destination.parent
    destination_parent.mkdir(parents=True, exist_ok=True)

    if destination.exists() and destination.is_symlink():
        raise RecoveryBundleError("destination symlink is forbidden")
    if destination.exists() and destination.is_dir():
        raise RecoveryBundleError("destination must be a file path")

    manifest_bytes = manifest.to_json().encode("utf-8")
    manifest_sha = _sha256(manifest_bytes)

    payloads: list[tuple[str, bytes]] = []
    members: list[RecoveryBundleMember] = []

    for rel_path in manifest.required_paths:
        normalized = _portable_rel_path(rel_path)
        data = _read_payload_file(project_root, normalized)
        member_path = PAYLOAD_PREFIX + normalized
        payloads.append((member_path, data))
        members.append(
            RecoveryBundleMember(
                path=normalized,
                sha256=_sha256(data),
                size=len(data),
            )
        )

    index_payload = {
        "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
        "manifest_member": MANIFEST_MEMBER,
        "manifest_sha256": manifest_sha,
        "payload_prefix": PAYLOAD_PREFIX,
        "members": [
            {
                "path": member.path,
                "sha256": member.sha256,
                "size": member.size,
            }
            for member in members
        ],
    }
    index_bytes = _json_bytes(index_payload)

    temp_path = destination.with_name(destination.name + ".tmp")
    if temp_path.exists():
        if temp_path.is_dir():
            raise RecoveryBundleError(
                "temporary bundle path is a directory"
            )
        temp_path.unlink()

    try:
        with zipfile.ZipFile(
            temp_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.writestr(MANIFEST_MEMBER, manifest_bytes)
            archive.writestr(INDEX_MEMBER, index_bytes)
            for member_path, data in payloads:
                archive.writestr(member_path, data)

        temp_path.replace(destination)
    except Exception:
        if temp_path.exists() and temp_path.is_file():
            temp_path.unlink()
        raise

    return RecoveryBundleExport(
        bundle_path=destination,
        members=tuple(members),
        manifest_sha256=manifest_sha,
    )


__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "INDEX_MEMBER",
    "MANIFEST_MEMBER",
    "PAYLOAD_PREFIX",
    "RecoveryBundleError",
    "RecoveryBundleExport",
    "RecoveryBundleMember",
    "export_recovery_bundle",
]
