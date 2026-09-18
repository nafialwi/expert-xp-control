from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .recovery_bundle import (
    BUNDLE_SCHEMA_VERSION,
    INDEX_MEMBER,
    MANIFEST_MEMBER,
    PAYLOAD_PREFIX,
)
from .recovery_manifest import RecoveryManifestV1

_MAX_MEMBER_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_PAYLOAD_BYTES = 64 * 1024 * 1024
_MAX_MEMBER_COUNT = 512
_TEXT_SCAN_LIMIT = 2 * 1024 * 1024

_SECRET_PATTERNS = (
    re.compile(
        rb"(?i)(api[_-]?key|token|password|passwd|authorization)"
        rb"\s*[:=]\s*[\"']?[A-Za-z0-9._\-]{24,}"
    ),
    re.compile(rb"(?i)bearer\s+[A-Za-z0-9._\-]{24,}"),
    re.compile(rb"\bsk-[A-Za-z0-9]{24,}\b"),
)


class RecoveryImportError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedRecoveryMember:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class VerifiedRecoveryBundle:
    manifest: RecoveryManifestV1
    members: tuple[VerifiedRecoveryMember, ...]
    manifest_sha256: str


@dataclass(frozen=True)
class RecoveryRestoreResult:
    destination: Path
    manifest: RecoveryManifestV1
    restored_paths: tuple[str, ...]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _portable_member_name(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise RecoveryImportError("archive member name must be non-empty")
    if "\\" in name:
        raise RecoveryImportError(
            "archive member must use POSIX separators"
        )
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise RecoveryImportError("archive member must be relative")

    path = PurePosixPath(name)
    if path.is_absolute() or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise RecoveryImportError(
            "archive member contains traversal or dot segments"
        )
    return path.as_posix()


def _read_json_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryImportError(
            f"{label} is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(value, dict):
        raise RecoveryImportError(f"{label} must be a JSON object")
    return value


def _scan_secret_like(data: bytes, path: str) -> None:
    if len(data) > _TEXT_SCAN_LIMIT:
        return
    for pattern in _SECRET_PATTERNS:
        if pattern.search(data):
            raise RecoveryImportError(
                f"secret-like content detected during import: {path}"
            )


def verify_recovery_bundle(
    bundle_path: Path,
) -> VerifiedRecoveryBundle:
    if not isinstance(bundle_path, Path):
        raise TypeError("bundle_path must be pathlib.Path")
    if bundle_path.is_symlink():
        raise RecoveryImportError("bundle symlink is forbidden")
    if not bundle_path.exists() or not bundle_path.is_file():
        raise RecoveryImportError(
            "bundle_path must be an existing file"
        )

    try:
        archive = zipfile.ZipFile(bundle_path, mode="r")
    except zipfile.BadZipFile as exc:
        raise RecoveryImportError("bundle is not a valid ZIP") from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > _MAX_MEMBER_COUNT:
            raise RecoveryImportError(
                "bundle exceeds member-count limit"
            )

        raw_names = [info.filename for info in infos]
        if len(set(raw_names)) != len(raw_names):
            raise RecoveryImportError(
                "duplicate archive member names are forbidden"
            )

        names = tuple(_portable_member_name(name) for name in raw_names)
        name_set = set(names)

        if MANIFEST_MEMBER not in name_set:
            raise RecoveryImportError("manifest member is missing")
        if INDEX_MEMBER not in name_set:
            raise RecoveryImportError("index member is missing")

        for info in infos:
            if info.is_dir():
                raise RecoveryImportError(
                    f"directory archive member is forbidden: {info.filename}"
                )
            if info.file_size > _MAX_MEMBER_BYTES:
                raise RecoveryImportError(
                    f"archive member exceeds size limit: {info.filename}"
                )

        manifest_bytes = archive.read(MANIFEST_MEMBER)
        index_bytes = archive.read(INDEX_MEMBER)

        try:
            manifest = RecoveryManifestV1.from_json(
                manifest_bytes.decode("utf-8")
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise RecoveryImportError(
                "recovery manifest validation failed"
            ) from exc

        index = _read_json_object(index_bytes, "bundle index")

        expected_index_keys = {
            "bundle_schema_version",
            "manifest_member",
            "manifest_sha256",
            "payload_prefix",
            "members",
        }
        if set(index) != expected_index_keys:
            raise RecoveryImportError(
                "bundle index fields do not match schema"
            )
        if index["bundle_schema_version"] != BUNDLE_SCHEMA_VERSION:
            raise RecoveryImportError(
                "unsupported bundle schema version"
            )
        if index["manifest_member"] != MANIFEST_MEMBER:
            raise RecoveryImportError(
                "bundle index manifest member mismatch"
            )
        if index["payload_prefix"] != PAYLOAD_PREFIX:
            raise RecoveryImportError(
                "bundle index payload prefix mismatch"
            )

        manifest_sha = _sha256(manifest_bytes)
        if index["manifest_sha256"] != manifest_sha:
            raise RecoveryImportError(
                "manifest checksum mismatch"
            )

        raw_members = index["members"]
        if not isinstance(raw_members, list):
            raise RecoveryImportError(
                "bundle index members must be a list"
            )

        expected_paths = list(manifest.required_paths)
        indexed_paths: list[str] = []
        verified: list[VerifiedRecoveryMember] = []
        total_size = 0

        for item in raw_members:
            if not isinstance(item, dict):
                raise RecoveryImportError(
                    "bundle index member must be an object"
                )
            if set(item) != {"path", "sha256", "size"}:
                raise RecoveryImportError(
                    "bundle index member fields do not match schema"
                )

            rel_path = item["path"]
            if not isinstance(rel_path, str):
                raise RecoveryImportError(
                    "bundle index member path must be a string"
                )
            rel_path = _portable_member_name(rel_path)
            if rel_path.startswith(PAYLOAD_PREFIX):
                raise RecoveryImportError(
                    "bundle index member path must be payload-relative"
                )

            indexed_paths.append(rel_path)
            archive_name = PAYLOAD_PREFIX + rel_path
            if archive_name not in name_set:
                raise RecoveryImportError(
                    f"payload archive member is missing: {rel_path}"
                )

            info = archive.getinfo(archive_name)
            expected_size = item["size"]
            if not isinstance(expected_size, int) or expected_size < 0:
                raise RecoveryImportError(
                    f"invalid payload size in index: {rel_path}"
                )
            if expected_size != info.file_size:
                raise RecoveryImportError(
                    f"payload size mismatch: {rel_path}"
                )

            data = archive.read(archive_name)
            if len(data) != expected_size:
                raise RecoveryImportError(
                    f"payload read-size mismatch: {rel_path}"
                )

            expected_sha = item["sha256"]
            if not isinstance(expected_sha, str) or not re.fullmatch(
                r"[0-9a-f]{64}", expected_sha
            ):
                raise RecoveryImportError(
                    f"invalid payload checksum: {rel_path}"
                )
            actual_sha = _sha256(data)
            if actual_sha != expected_sha:
                raise RecoveryImportError(
                    f"payload checksum mismatch: {rel_path}"
                )

            _scan_secret_like(data, rel_path)

            total_size += len(data)
            if total_size > _MAX_TOTAL_PAYLOAD_BYTES:
                raise RecoveryImportError(
                    "bundle exceeds total payload size limit"
                )

            verified.append(
                VerifiedRecoveryMember(
                    path=rel_path,
                    sha256=actual_sha,
                    size=len(data),
                )
            )

        if indexed_paths != expected_paths:
            raise RecoveryImportError(
                "bundle index paths do not match manifest required_paths"
            )

        expected_names = {
            MANIFEST_MEMBER,
            INDEX_MEMBER,
            *{PAYLOAD_PREFIX + path for path in expected_paths},
        }
        extras = name_set - expected_names
        missing = expected_names - name_set
        if extras:
            raise RecoveryImportError(
                "unexpected archive members: " + ",".join(sorted(extras))
            )
        if missing:
            raise RecoveryImportError(
                "required archive members missing: "
                + ",".join(sorted(missing))
            )

        return VerifiedRecoveryBundle(
            manifest=manifest,
            members=tuple(verified),
            manifest_sha256=manifest_sha,
        )


def restore_recovery_bundle(
    *,
    bundle_path: Path,
    destination: Path,
) -> RecoveryRestoreResult:
    if not isinstance(destination, Path):
        raise TypeError("destination must be pathlib.Path")
    if destination.is_symlink():
        raise RecoveryImportError(
            "destination symlink is forbidden"
        )
    if destination.exists():
        if not destination.is_dir():
            raise RecoveryImportError(
                "destination must be a directory path"
            )
        if any(destination.iterdir()):
            raise RecoveryImportError(
                "destination must be empty"
            )

    verified = verify_recovery_bundle(bundle_path)

    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=".xp-recovery-",
            dir=str(parent),
        )
    )

    try:
        with zipfile.ZipFile(bundle_path, mode="r") as archive:
            for member in verified.members:
                data = archive.read(PAYLOAD_PREFIX + member.path)
                target = staging.joinpath(
                    *PurePosixPath(member.path).parts
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)

                if target.is_symlink():
                    raise RecoveryImportError(
                        f"restored payload became symlink: {member.path}"
                    )
                if _sha256(target.read_bytes()) != member.sha256:
                    raise RecoveryImportError(
                        f"post-write checksum mismatch: {member.path}"
                    )

        (staging / MANIFEST_MEMBER).write_text(
            verified.manifest.to_json(),
            encoding="utf-8",
        )

        if destination.exists():
            destination.rmdir()
        staging.replace(destination)

    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise

    return RecoveryRestoreResult(
        destination=destination,
        manifest=verified.manifest,
        restored_paths=tuple(
            member.path for member in verified.members
        ),
    )


__all__ = [
    "RecoveryImportError",
    "RecoveryRestoreResult",
    "VerifiedRecoveryBundle",
    "VerifiedRecoveryMember",
    "restore_recovery_bundle",
    "verify_recovery_bundle",
]
