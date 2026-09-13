from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .checkpoint import read_checkpoint_state_v1
from .models import RunState, read_run_state_v1
from .packages import read_package_manifest_v1
from .project_registry import (
    ProjectProfile,
    parse_registry_v1,
    read_project_profile_v1,
    read_registry_v1,
)


@dataclass(frozen=True)
class CompatibilityCheck:
    code: str
    status: str
    detail: str


@dataclass(frozen=True)
class CompatibilityReport:
    status: str
    target: str
    checks: tuple[CompatibilityCheck, ...]
    read_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "target": self.target,
            "read_only": self.read_only,
            "checks": [
                {
                    "code": item.code,
                    "status": item.status,
                    "detail": item.detail,
                }
                for item in self.checks
            ],
        }


@dataclass(frozen=True)
class ControlStateV1:
    control_version: int
    registry: dict[str, Any]
    runs: tuple[RunState, ...]


@dataclass(frozen=True)
class IncidentHandoffV1:
    project_id: str
    run_id: str
    stage: str
    incident_id: str
    incident_challenge: str
    members: tuple[str, ...]


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_control_state_v1(path: Path) -> ControlStateV1:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid control-state JSON: {path}") from exc

    if int(data.get("control_version", 0)) != 1:
        raise ValueError("unsupported control-state version")

    registry = parse_registry_v1(dict(data.get("registry") or {}))
    runs: list[RunState] = []
    for raw in data.get("runs") or []:
        if not isinstance(raw, dict):
            raise ValueError("control-state run entry must be an object")
        runs.append(RunState.from_dict(dict(raw)))

    return ControlStateV1(1, registry, tuple(runs))


def read_incident_handoff_v1(path: Path) -> IncidentHandoffV1:
    path = Path(path)
    required = {
        "00_READ_FIRST.md",
        "GPT_INSTRUCTIONS.md",
        "PROJECT_CONTEXT.json",
        "TECHNICAL_STATE.json",
    }
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = set(zf.namelist())
            missing = sorted(required - names)
            if missing:
                raise ValueError(
                    "incident handoff missing member(s): " + ", ".join(missing)
                )
            context = json.loads(
                zf.read("PROJECT_CONTEXT.json").decode("utf-8")
            )
            json.loads(zf.read("TECHNICAL_STATE.json").decode("utf-8"))
    except zipfile.BadZipFile as exc:
        raise ValueError("invalid incident ZIP") from exc
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
        raise ValueError("invalid incident handoff payload") from exc

    if context.get("kind") != "INCIDENT":
        raise ValueError("handoff kind is not INCIDENT")
    if context.get("stage") != "WAITING_GPT":
        raise ValueError("incident handoff stage must be WAITING_GPT")

    keys = ("project_id", "run_id", "incident_id", "incident_challenge")
    missing_values = [k for k in keys if not str(context.get(k) or "").strip()]
    if missing_values:
        raise ValueError(
            "incident handoff missing binding(s): " + ", ".join(missing_values)
        )

    return IncidentHandoffV1(
        project_id=str(context["project_id"]),
        run_id=str(context["run_id"]),
        stage=str(context["stage"]),
        incident_id=str(context["incident_id"]),
        incident_challenge=str(context["incident_challenge"]),
        members=tuple(sorted(names)),
    )


class CompatibilityAudit:
    """Read-only compatibility audit for frozen v1 artifacts."""

    def __init__(self, home: Path | None = None):
        self.home = (
            Path(home).expanduser().resolve()
            if home is not None
            else Path.home().resolve()
        )

    @staticmethod
    def _file_state(root: Path) -> dict[str, tuple[str, int, int]]:
        """Return hash + mtime_ns + size without writing anything."""
        root = Path(root)
        if root.is_file():
            stat = root.stat()
            return {
                root.name: (
                    _sha256(root),
                    stat.st_mtime_ns,
                    stat.st_size,
                )
            }

        values: dict[str, tuple[str, int, int]] = {}
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            stat = path.stat()
            values[path.relative_to(root).as_posix()] = (
                _sha256(path),
                stat.st_mtime_ns,
                stat.st_size,
            )
        return values

    @staticmethod
    def _run_check(
        checks: list[CompatibilityCheck],
        code: str,
        path: Path,
        reader: Callable[[Path], Any],
    ) -> None:
        if not path.is_file():
            checks.append(
                CompatibilityCheck(code, "SKIPPED", f"not present: {path}")
            )
            return
        try:
            value = reader(path)
        except Exception as exc:
            checks.append(CompatibilityCheck(code, "ERROR", str(exc)))
            return

        detail = f"readable: {path.name}"
        if isinstance(value, RunState):
            detail += (
                f"; state_version={value.state_version}; stage={value.stage}"
            )
        elif isinstance(value, ProjectProfile):
            detail += f"; profile_version={value.profile_version}"
        checks.append(CompatibilityCheck(code, "CLEAR", detail))

    def run(self, repo_or_fixture: Path) -> CompatibilityReport:
        target = Path(repo_or_fixture).expanduser().resolve()
        if not target.exists():
            return CompatibilityReport(
                "ERROR",
                str(target),
                (
                    CompatibilityCheck(
                        "TARGET", "ERROR", "target does not exist"
                    ),
                ),
            )

        before = self._file_state(target)
        checks: list[CompatibilityCheck] = []

        if target.is_file():
            name = target.name
            readers = {
                "project.json": ("PROFILE_V1", read_project_profile_v1),
                "state.json": ("STATE_V1", read_run_state_v1),
                "locked_remote.json": ("STATE_V1", read_run_state_v1),
                "CHECKPOINT_STATE.json": (
                    "CHECKPOINT_V1",
                    read_checkpoint_state_v1,
                ),
                "manifest.json": (
                    "PACKAGE_PROTOCOL_V1",
                    read_package_manifest_v1,
                ),
                "registry.json": ("REGISTRY_V1", read_registry_v1),
                "xp-control-state.json": (
                    "CONTROL_STATE_V1",
                    read_control_state_v1,
                ),
            }
            if name in readers:
                code, reader = readers[name]
                self._run_check(checks, code, target, reader)
            elif target.suffix.lower() == ".zip":
                self._run_check(
                    checks, "INCIDENT_ZIP_V1", target, read_incident_handoff_v1
                )
            else:
                checks.append(
                    CompatibilityCheck(
                        "TARGET",
                        "ERROR",
                        f"unsupported compatibility target: {name}",
                    )
                )
        else:
            profile = target / ".xp" / "project.json"
            if profile.is_file():
                self._run_check(
                    checks, "PROFILE_V1", profile, read_project_profile_v1
                )

            fixture_map = (
                (
                    "PROFILE_V1",
                    target / "profile_v1" / "project.json",
                    read_project_profile_v1,
                ),
                (
                    "STATE_V1",
                    target / "state_v1" / "locked_remote.json",
                    read_run_state_v1,
                ),
                (
                    "CHECKPOINT_V1",
                    target / "checkpoint_v1" / "CHECKPOINT_STATE.json",
                    read_checkpoint_state_v1,
                ),
                (
                    "PACKAGE_PROTOCOL_V1",
                    target / "package_v1" / "manifest.json",
                    read_package_manifest_v1,
                ),
                (
                    "REGISTRY_V1",
                    target / "registry_v1" / "registry.json",
                    read_registry_v1,
                ),
                (
                    "CONTROL_STATE_V1",
                    target / "control_v1" / "xp-control-state.json",
                    read_control_state_v1,
                ),
            )
            for code, path, reader in fixture_map:
                if path.is_file():
                    self._run_check(checks, code, path, reader)

            for incident in sorted(target.glob("incident_v1/*.zip")):
                self._run_check(
                    checks,
                    "INCIDENT_ZIP_V1",
                    incident,
                    read_incident_handoff_v1,
                )

        after = self._file_state(target)
        read_only = before == after
        checks.append(
            CompatibilityCheck(
                "READ_ONLY",
                "CLEAR" if read_only else "ERROR",
                "target bytes unchanged"
                if read_only
                else "compatibility audit changed target bytes",
            )
        )

        errors = [x for x in checks if x.status == "ERROR"]
        clears = [x for x in checks if x.status == "CLEAR"]
        status = "CLEAR" if clears and not errors and read_only else "ERROR"
        return CompatibilityReport(
            status=status,
            target=str(target),
            checks=tuple(checks),
            read_only=read_only,
        )
