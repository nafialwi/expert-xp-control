from __future__ import annotations

import json
import re
from dataclasses import MISSING, dataclass
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping

SCHEMA_VERSION = 1
SOURCE_KIND = "github"

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
_PROJECT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_CHECKPOINT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_SECRET_KEY_RE = re.compile(
    r"(secret|token|password|passwd|api[_-]?key|authorization|credential)",
    re.IGNORECASE,
)


class RecoveryManifestError(ValueError):
    pass


def _require_text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecoveryManifestError(f"{name} must be a non-empty string")
    return value.strip()


def _validate_portable_path(value: str) -> str:
    value = _require_text("required_path", value)

    if "\\" in value:
        raise RecoveryManifestError("required_path must use POSIX separators")
    if value.startswith("/"):
        raise RecoveryManifestError("required_path must be relative")
    if re.match(r"^[A-Za-z]:", value):
        raise RecoveryManifestError("required_path must not use a drive path")

    path = PurePosixPath(value)
    if path.is_absolute():
        raise RecoveryManifestError("required_path must be relative")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise RecoveryManifestError(
            "required_path must not contain traversal or dot segments"
        )
    return path.as_posix()


def _validate_public_metadata(
    metadata: Mapping[str, str] | None,
) -> Mapping[str, str]:
    if metadata is None:
        return MappingProxyType({})
    if not isinstance(metadata, Mapping):
        raise RecoveryManifestError("metadata must be a mapping")

    normalized: dict[str, str] = {}
    for raw_key, raw_value in metadata.items():
        key = _require_text("metadata key", raw_key)
        value = _require_text(f"metadata[{key}]", raw_value)

        if _SECRET_KEY_RE.search(key):
            raise RecoveryManifestError(
                f"secret-like metadata key is forbidden: {key}"
            )

        lower_value = value.lower()
        if (
            "bearer " in lower_value
            or re.search(r"\bsk-[A-Za-z0-9]{12,}\b", value)
        ):
            raise RecoveryManifestError(
                f"secret-like metadata value is forbidden: {key}"
            )

        normalized[key] = value

    return MappingProxyType(dict(sorted(normalized.items())))


@dataclass(frozen=True)
class RecoveryManifestV1:
    project_id: str
    checkpoint: str
    repo_slug: str
    branch: str
    commit_sha: str
    created_at_utc: str
    required_paths: tuple[str, ...] = ()
    metadata: Mapping[str, str] | None = None
    schema_version: int = SCHEMA_VERSION
    source_kind: str = SOURCE_KIND

    def __post_init__(self) -> None:
        project_id = _require_text("project_id", self.project_id)
        checkpoint = _require_text("checkpoint", self.checkpoint)
        repo_slug = _require_text("repo_slug", self.repo_slug)
        branch = _require_text("branch", self.branch)
        commit_sha = _require_text("commit_sha", self.commit_sha).lower()
        created_at_utc = _require_text("created_at_utc", self.created_at_utc)

        if not _PROJECT_RE.fullmatch(project_id):
            raise RecoveryManifestError("project_id contains invalid characters")
        if not _CHECKPOINT_RE.fullmatch(checkpoint):
            raise RecoveryManifestError("checkpoint contains invalid characters")
        if not _REPO_RE.fullmatch(repo_slug):
            raise RecoveryManifestError(
                "repo_slug must use owner/repository format"
            )
        if not _BRANCH_RE.fullmatch(branch):
            raise RecoveryManifestError("branch contains invalid characters")
        if branch.startswith("/") or branch.endswith("/") or ".." in branch:
            raise RecoveryManifestError("branch is not a portable git ref")
        if not _SHA40_RE.fullmatch(commit_sha):
            raise RecoveryManifestError(
                "commit_sha must be a full 40-character lowercase/hex SHA"
            )
        if not created_at_utc.endswith("Z"):
            raise RecoveryManifestError(
                "created_at_utc must be an explicit UTC timestamp ending in Z"
            )
        if self.schema_version != SCHEMA_VERSION:
            raise RecoveryManifestError(
                f"unsupported schema_version: {self.schema_version}"
            )
        if self.source_kind != SOURCE_KIND:
            raise RecoveryManifestError(
                f"unsupported source_kind: {self.source_kind}"
            )

        if not isinstance(self.required_paths, tuple):
            raise RecoveryManifestError("required_paths must be a tuple")

        normalized_paths = tuple(
            _validate_portable_path(path) for path in self.required_paths
        )
        if len(set(normalized_paths)) != len(normalized_paths):
            raise RecoveryManifestError("required_paths must be unique")

        normalized_metadata = _validate_public_metadata(self.metadata)

        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "checkpoint", checkpoint)
        object.__setattr__(self, "repo_slug", repo_slug)
        object.__setattr__(self, "branch", branch)
        object.__setattr__(self, "commit_sha", commit_sha)
        object.__setattr__(self, "created_at_utc", created_at_utc)
        object.__setattr__(self, "required_paths", normalized_paths)
        object.__setattr__(self, "metadata", normalized_metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_kind": self.source_kind,
            "project_id": self.project_id,
            "checkpoint": self.checkpoint,
            "repo_slug": self.repo_slug,
            "branch": self.branch,
            "commit_sha": self.commit_sha,
            "created_at_utc": self.created_at_utc,
            "required_paths": list(self.required_paths),
            "metadata": dict(self.metadata or {}),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RecoveryManifestV1":
        if not isinstance(payload, Mapping):
            raise RecoveryManifestError("manifest payload must be a mapping")

        expected = {
            "schema_version",
            "source_kind",
            "project_id",
            "checkpoint",
            "repo_slug",
            "branch",
            "commit_sha",
            "created_at_utc",
            "required_paths",
            "metadata",
        }
        unknown = set(payload) - expected
        missing = expected - set(payload)
        if unknown:
            raise RecoveryManifestError(
                "unknown manifest fields: " + ",".join(sorted(unknown))
            )
        if missing:
            raise RecoveryManifestError(
                "missing manifest fields: " + ",".join(sorted(missing))
            )

        raw_paths = payload["required_paths"]
        if not isinstance(raw_paths, list):
            raise RecoveryManifestError(
                "required_paths JSON value must be a list"
            )

        return cls(
            schema_version=payload["schema_version"],
            source_kind=payload["source_kind"],
            project_id=payload["project_id"],
            checkpoint=payload["checkpoint"],
            repo_slug=payload["repo_slug"],
            branch=payload["branch"],
            commit_sha=payload["commit_sha"],
            created_at_utc=payload["created_at_utc"],
            required_paths=tuple(raw_paths),
            metadata=payload["metadata"],
        )

    @classmethod
    def from_json(cls, text: str) -> "RecoveryManifestV1":
        if not isinstance(text, str) or not text.strip():
            raise RecoveryManifestError("manifest JSON must be non-empty")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RecoveryManifestError("invalid manifest JSON") from exc
        return cls.from_dict(payload)


__all__ = [
    "RecoveryManifestError",
    "RecoveryManifestV1",
    "SCHEMA_VERSION",
    "SOURCE_KIND",
]
