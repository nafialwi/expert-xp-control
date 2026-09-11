from __future__ import annotations

import hashlib
import json
import shutil
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from . import __version__

ALLOWED_OPERATIONS = {
    "APPLY_PATCH",
    "ADD_FILE",
    "REPLACE_FILE",
    "DELETE_ALLOWED_FILE",
    "REGISTER_MIGRATION",
    "RUN_SOURCE_VERIFY",
    "APPLY_DB_MIGRATION",
    "RUN_SQL_TEST",
    "GENERATE_CHECKPOINT",
}


class PackageError(ValueError):
    pass


class UnsafeArchiveError(PackageError):
    pass


@dataclass(frozen=True)
class RunContext:
    project_id: str
    stage: str
    base_fingerprint: str
    run_id: str | None = None
    incident_id: str | None = None
    incident_challenge: str | None = None
    human_qa: tuple[str, ...] = ()


@dataclass(frozen=True)
class PackageManifest:
    path: Path
    protocol_version: int
    min_xp_version: str
    package_type: str
    project_id: str
    run_id: str | None
    milestone: str | None
    base_fingerprint: str
    expected_state: str
    allowed_paths: tuple[str, ...]
    operations: tuple[dict[str, Any], ...]
    checksums: dict[str, str]
    incident_id: str | None = None
    incident_challenge: str | None = None
    human_qa: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationReport:
    status: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class StagedPackage:
    root: Path
    manifest: PackageManifest


def _version_tuple(value: str) -> tuple[int, int, int]:
    raw = value.split("-", 1)[0]
    parts = raw.split(".")
    nums = [int(p) if p.isdigit() else 0 for p in parts[:3]]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)  # type: ignore[return-value]


def _safe_member_name(name: str) -> PurePosixPath:
    if not name or "\\" in name:
        raise UnsafeArchiveError(f"Unsafe archive member: {name!r}")
    p = PurePosixPath(name)
    if p.is_absolute() or any(part in {"", ".", ".."} for part in p.parts):
        raise UnsafeArchiveError(f"Unsafe archive member: {name!r}")
    return p


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def inspect_package(path: Path) -> PackageManifest:
    path = Path(path)
    try:
        with zipfile.ZipFile(path, "r") as zf:
            try:
                raw = zf.read("manifest.json")
            except KeyError as exc:
                raise PackageError("Missing manifest.json") from exc
    except zipfile.BadZipFile as exc:
        raise PackageError("Invalid ZIP package") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise PackageError("Invalid package manifest JSON") from exc
    required = [
        "protocol_version",
        "min_xp_version",
        "package_type",
        "project_id",
        "base_fingerprint",
        "expected_state",
        "allowed_paths",
        "operations",
        "checksums",
    ]
    missing = [key for key in required if key not in data]
    if missing:
        raise PackageError(f"Missing manifest fields: {', '.join(missing)}")
    return PackageManifest(
        path=path,
        protocol_version=int(data["protocol_version"]),
        min_xp_version=str(data["min_xp_version"]),
        package_type=str(data["package_type"]),
        project_id=str(data["project_id"]),
        run_id=data.get("run_id"),
        milestone=data.get("milestone"),
        base_fingerprint=str(data["base_fingerprint"]),
        expected_state=str(data["expected_state"]),
        allowed_paths=tuple(str(v) for v in data["allowed_paths"]),
        operations=tuple(dict(v) for v in data["operations"]),
        checksums={str(k): str(v) for k, v in dict(data["checksums"]).items()},
        incident_id=data.get("incident_id"),
        incident_challenge=data.get("incident_challenge"),
        human_qa=tuple(str(v) for v in data.get("human_qa", [])),
    )


def validate_package(manifest: PackageManifest, context: RunContext) -> ValidationReport:
    reasons: list[str] = []
    if manifest.protocol_version != 1:
        reasons.append("unsupported package protocol")
    if _version_tuple(__version__) < _version_tuple(manifest.min_xp_version):
        reasons.append("XP version is too old")
    if manifest.project_id != context.project_id:
        reasons.append("project mismatch")
    if manifest.base_fingerprint != context.base_fingerprint:
        reasons.append("base source mismatch")
    if manifest.expected_state != context.stage:
        reasons.append("workflow state mismatch")
    engine_executable = {
        "APPLY_PATCH", "ADD_FILE", "REPLACE_FILE", "DELETE_ALLOWED_FILE",
        "APPLY_DB_MIGRATION", "RUN_SQL_TEST",
    }
    for operation in manifest.operations:
        if operation.get("type") not in ALLOWED_OPERATIONS:
            reasons.append(f"unsupported operation {operation.get('type')}")
        elif operation.get("type") not in engine_executable:
            reasons.append(f"operation declared but not executed by engine V2: {operation.get('type')}")
        path = operation.get("path")
        if path is not None:
            try:
                member = _safe_member_name(str(path))
            except UnsafeArchiveError:
                reasons.append("unsafe operation path")
                continue
            if not any(str(member).startswith(prefix.rstrip("/") + "/") or str(member) == prefix.rstrip("/") for prefix in manifest.allowed_paths):
                reasons.append(f"operation path outside allowed scope: {path}")
    if manifest.package_type == "REMEDIATION":
        if not context.run_id or not context.incident_id or not context.incident_challenge:
            reasons.append("no active incident context")
        if manifest.run_id != context.run_id:
            reasons.append("run mismatch")
        if manifest.incident_id != context.incident_id:
            reasons.append("incident mismatch")
        if manifest.incident_challenge != context.incident_challenge:
            reasons.append("incident challenge mismatch")
    return ValidationReport("ERROR" if reasons else "CLEAR", tuple(reasons))


def stage_package(path: Path, staging_root: Path) -> StagedPackage:
    manifest = inspect_package(path)
    staging_root = Path(staging_root)
    if staging_root.exists():
        shutil.rmtree(staging_root)
    staging_root.mkdir(parents=True, exist_ok=True)
    root_resolved = staging_root.resolve()
    with zipfile.ZipFile(path, "r") as zf:
        infos = zf.infolist()
        for info in infos:
            member = _safe_member_name(info.filename)
            if _is_zip_symlink(info):
                raise UnsafeArchiveError(f"Symlink not allowed: {info.filename}")
            target = (staging_root / Path(*member.parts)).resolve()
            if target != root_resolved and root_resolved not in target.parents:
                raise UnsafeArchiveError(f"Archive escapes staging root: {info.filename}")
            if not info.is_dir() and info.filename != "manifest.json" and info.filename not in manifest.checksums:
                raise PackageError(f"Unchecksummed package file: {info.filename}")
        for name in manifest.checksums:
            _safe_member_name(name)
        for info in infos:
            member = _safe_member_name(info.filename)
            target = staging_root / Path(*member.parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            data = zf.read(info)
            expected = manifest.checksums.get(info.filename)
            if info.filename != "manifest.json" and expected is not None:
                actual = hashlib.sha256(data).hexdigest()
                if actual != expected:
                    raise PackageError(f"Checksum mismatch: {info.filename}")
            target.write_bytes(data)
    for name, expected in manifest.checksums.items():
        target = staging_root / name
        if not target.exists():
            raise PackageError(f"Missing checksummed file: {name}")
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != expected:
            raise PackageError(f"Checksum mismatch: {name}")
    return StagedPackage(staging_root, manifest)
