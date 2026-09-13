from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .paths import XPPaths


class ProjectIdentityError(ValueError):
    pass


class ProjectProfileError(ValueError):
    pass


@dataclass(frozen=True)
class ProjectProfile:
    project_id: str
    name: str
    profile_version: int = 1
    runtimes: tuple[str, ...] = ()
    source_adapter: str | None = None
    database_adapter: str | None = None
    verify_adapter: str | None = None
    deployment_adapter: str | None = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectProfile":
        if int(data.get("profile_version", 1)) != 1:
            raise ProjectProfileError("Unsupported project profile version")
        project_id = str(data.get("project_id", "")).strip()
        name = str(data.get("name", "")).strip()
        if not project_id or not name:
            raise ProjectProfileError("project_id and name are required")
        return cls(
            project_id=project_id,
            name=name,
            profile_version=1,
            runtimes=tuple(str(v) for v in data.get("runtimes", [])),
            source_adapter=data.get("source_adapter"),
            database_adapter=data.get("database_adapter"),
            verify_adapter=data.get("verify_adapter"),
            deployment_adapter=data.get("deployment_adapter"),
            metadata=dict(data.get("metadata") or {}),
        )

    def to_dict(self) -> dict:
        value = asdict(self)
        value["runtimes"] = list(self.runtimes)
        return value


@dataclass(frozen=True)
class ProjectSummary:
    project_id: str
    name: str
    repo_path: str | None
    last_active_at: str | None
    status: str = "LOCAL"
    remote_url: str | None = None


def load_project_profile(repo: Path) -> ProjectProfile:
    path = Path(repo) / ".xp" / "project.json"
    if not path.exists():
        raise ProjectProfileError(f"Missing project profile: {path}")
    return ProjectProfile.from_dict(json.loads(path.read_text(encoding="utf-8")))


def validate_project_identity(expected_project_id: str, profile: ProjectProfile) -> None:
    if profile.project_id != expected_project_id:
        raise ProjectIdentityError(
            f"Project identity mismatch: expected {expected_project_id}, got {profile.project_id}"
        )


class ProjectRegistry:
    def __init__(self, paths: XPPaths):
        self.paths = paths
        self.path = paths.root / "registry.json"

    @classmethod
    def for_home(cls, home: Path) -> "ProjectRegistry":
        return cls(XPPaths.from_home(home))

    def _load(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "projects": {}, "last_active": None}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("version") != 1:
            raise ProjectProfileError("Unsupported registry version")
        return data

    def _save(self, data: dict) -> None:
        self.paths.ensure_runtime_dirs()
        tmp = self.path.with_suffix(f".{os.getpid()}.tmp")
        payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)

    @staticmethod
    def _remote_url(repo_path: Path | None) -> str | None:
        if not repo_path:
            return None
        try:
            completed = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=Path(repo_path),
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        return completed.stdout.strip() or None

    def assert_can_register(self, profile: ProjectProfile) -> None:
        data = self._load()
        current = data["projects"].get(profile.project_id)
        if current and current.get("name") != profile.name:
            raise ProjectIdentityError(f"Project ID {profile.project_id} already registered")

    def register(self, profile: ProjectProfile, repo_path: Path | None) -> None:
        self.assert_can_register(profile)
        data = self._load()
        now = datetime.now(timezone.utc).isoformat()
        data["projects"][profile.project_id] = {
            "project_id": profile.project_id,
            "name": profile.name,
            "repo_path": str(Path(repo_path).resolve()) if repo_path else None,
            "last_active_at": now,
            "status": "LOCAL" if repo_path else "REMOTE_ONLY",
            "remote_url": self._remote_url(repo_path),
        }
        data["last_active"] = profile.project_id
        self._save(data)

    def activate(self, project_id: str) -> ProjectSummary:
        data = self._load()
        item = data["projects"].get(project_id)
        if not item:
            raise ProjectProfileError(f"Unknown project: {project_id}")
        now = datetime.now(timezone.utc).isoformat()
        item["last_active_at"] = now
        data["last_active"] = project_id
        self._save(data)
        return ProjectSummary(**item)

    def list_projects(self) -> list[ProjectSummary]:
        data = self._load()
        values = [ProjectSummary(**item) for item in data["projects"].values()]
        return sorted(values, key=lambda item: item.last_active_at or "", reverse=True)

    def last_active(self) -> ProjectSummary | None:
        data = self._load()
        project_id = data.get("last_active")
        if not project_id:
            return None
        item = data["projects"].get(project_id)
        return ProjectSummary(**item) if item else None

    def export_data(self) -> dict:
        return self._load()

    def restore_remote(self, data: dict) -> None:
        if data.get("version") != 1:
            raise ProjectProfileError("Unsupported registry version")
        restored = {"version": 1, "projects": {}, "last_active": data.get("last_active")}
        for project_id, item in (data.get("projects") or {}).items():
            restored["projects"][project_id] = {
                "project_id": str(item["project_id"]),
                "name": str(item["name"]),
                "repo_path": None,
                "last_active_at": item.get("last_active_at"),
                "status": "REMOTE_ONLY",
                "remote_url": item.get("remote_url"),
            }
        if restored["last_active"] not in restored["projects"]:
            restored["last_active"] = None
        self._save(restored)


def read_project_profile_v1(path_or_repo: Path) -> ProjectProfile:
    """Read profile_version=1 from repo or project.json path."""
    source = Path(path_or_repo)
    if source.is_dir():
        source = source / ".xp" / "project.json"
    if not source.is_file():
        raise ProjectProfileError(f"Missing project profile: {source}")
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectProfileError(
            f"Invalid project profile JSON: {source}"
        ) from exc
    return ProjectProfile.from_dict(dict(data))


def parse_registry_v1(data: dict) -> dict:
    """Validate registry version 1 without rewriting it."""
    if int(data.get("version", 0)) != 1:
        raise ProjectProfileError("Unsupported registry version")
    projects = data.get("projects")
    if not isinstance(projects, dict):
        raise ProjectProfileError("Registry projects must be an object")

    for key, item in projects.items():
        if not isinstance(item, dict):
            raise ProjectProfileError(
                f"Registry project {key} must be an object"
            )
        if not str(item.get("project_id") or "") or not str(
            item.get("name") or ""
        ):
            raise ProjectProfileError(
                f"Registry project {key} has incomplete identity"
            )

    last_active = data.get("last_active")
    if last_active is not None and str(last_active) not in projects:
        raise ProjectProfileError(
            "Registry last_active does not reference a project"
        )
    return dict(data)


def read_registry_v1(path: Path) -> dict:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectProfileError(
            f"Invalid registry JSON: {path}"
        ) from exc
    if not isinstance(data, dict):
        raise ProjectProfileError("Registry root must be an object")
    return parse_registry_v1(data)
