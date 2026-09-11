from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .models import RunState
from .paths import XPPaths
from .project_registry import ProjectRegistry
from .redaction import sanitize_mapping
from .state_store import StateStore

CONTROL_VERSION = 1


class ControlStateError(ValueError):
    pass


class ControlStateManager:
    """Portable, sanitized workflow state for device recovery.

    The control snapshot intentionally contains project references and run state,
    never repository contents or credentials.
    """

    def __init__(self, home: Path):
        self.paths = XPPaths.from_home(home)
        self.registry = ProjectRegistry(self.paths)
        self.store = StateStore(self.paths)

    def _runs(self) -> list[dict]:
        if not self.paths.runs.exists():
            return []
        values: list[dict] = []
        for state_path in sorted(self.paths.runs.glob("*/state.json")):
            try:
                data = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            values.append(sanitize_mapping(data))
        return values

    def export(self, output_dir: Path) -> Path:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        snapshot = output_dir / "xp-control-state.json"
        payload = {
            "control_version": CONTROL_VERSION,
            "registry": sanitize_mapping(self.registry.export_data()),
            "runs": self._runs(),
        }
        tmp = snapshot.with_suffix(f".{os.getpid()}.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, snapshot)
        return snapshot

    def sync_to_repo(self, control_repo: Path, *, push: bool = True) -> "ControlSyncResult":
        control_repo = Path(control_repo).expanduser().resolve()
        if not (control_repo / ".git").exists():
            raise ControlStateError("XP control repository is not a Git working tree")
        state_dir = control_repo / "state"
        snapshot = self.export(state_dir)
        _git(control_repo, "add", str(snapshot.relative_to(control_repo)))
        diff = _git(control_repo, "diff", "--cached", "--quiet", check=False)
        committed = diff.returncode != 0
        if committed:
            _git(control_repo, "commit", "-m", "xp: sync sanitized control state")
        pushed = False
        if push:
            _git(control_repo, "push")
            pushed = True
        return ControlSyncResult(committed=committed, pushed=pushed, path=snapshot)

    def restore(self, snapshot: Path) -> None:
        data = json.loads(Path(snapshot).read_text(encoding="utf-8"))
        if data.get("control_version") != CONTROL_VERSION:
            raise ControlStateError("Unsupported XP control-state version")
        self.registry.restore_remote(dict(data.get("registry") or {"version": 1, "projects": {}}))
        for raw in data.get("runs") or []:
            state = RunState.from_dict(dict(raw))
            self.store.save(state)


@dataclass(frozen=True)
class ControlSyncResult:
    committed: bool
    pushed: bool
    path: Path


class RemoteLeaseError(RuntimeError):
    pass


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True)
    if check and result.returncode != 0:
        raise ControlStateError(result.stderr.strip() or result.stdout.strip() or "git command failed")
    return result


def _atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


class RemoteLeaseManager:
    def __init__(self, control_repo: Path, *, device_id: str):
        self.repo = Path(control_repo).expanduser().resolve()
        self.device_id = str(device_id)

    def acquire(self, project_id: str, run_id: str, *, push: bool = True) -> Path:
        if push:
            pulled = _git(self.repo, "pull", "--ff-only", check=False)
            if pulled.returncode != 0:
                raise RemoteLeaseError(
                    "XP control repository tidak dapat fast-forward; lease tidak dibuat sampai state remote direkonsiliasi"
                )
        path = self.repo / "leases" / f"{project_id}.json"
        if path.exists():
            current = json.loads(path.read_text(encoding="utf-8"))
            if current.get("device_id") != self.device_id or current.get("run_id") != run_id:
                raise RemoteLeaseError(
                    f"Project {project_id} already has an active writer lease; recovery/takeover required"
                )
        payload = {
            "lease_version": 1,
            "project_id": project_id,
            "run_id": run_id,
            "device_id": self.device_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _atomic_json(path, payload)
        if push:
            _git(self.repo, "add", str(path.relative_to(self.repo)))
            diff = _git(self.repo, "diff", "--cached", "--quiet", check=False)
            if diff.returncode != 0:
                _git(self.repo, "commit", "-m", f"xp: lease {project_id} {run_id}")
            _git(self.repo, "push")
        return path

    def release(self, project_id: str, run_id: str, *, push: bool = True) -> None:
        path = self.repo / "leases" / f"{project_id}.json"
        if not path.exists():
            return
        current = json.loads(path.read_text(encoding="utf-8"))
        if current.get("device_id") != self.device_id or current.get("run_id") != run_id:
            raise RemoteLeaseError("Cannot release another device/run lease")
        path.unlink()
        if push:
            _git(self.repo, "add", "-A", "leases")
            diff = _git(self.repo, "diff", "--cached", "--quiet", check=False)
            if diff.returncode != 0:
                _git(self.repo, "commit", "-m", f"xp: release lease {project_id} {run_id}")
            _git(self.repo, "push")

    def takeover(self, project_id: str, run_id: str, *, push: bool = True) -> Path:
        """Human-authorized writer takeover when the previous device/run is lost."""
        if push:
            pulled = _git(self.repo, "pull", "--ff-only", check=False)
            if pulled.returncode != 0:
                raise RemoteLeaseError("Control repo tidak dapat fast-forward; takeover ditunda sampai state remote direkonsiliasi")
        path = self.repo / "leases" / f"{project_id}.json"
        archived = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        payload = {
            "lease_version": 1,
            "project_id": project_id,
            "run_id": run_id,
            "device_id": self.device_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "takeover_from": archived,
        }
        _atomic_json(path, payload)
        if push:
            _git(self.repo, "add", str(path.relative_to(self.repo)))
            diff = _git(self.repo, "diff", "--cached", "--quiet", check=False)
            if diff.returncode != 0:
                _git(self.repo, "commit", "-m", f"xp: lease takeover {project_id} {run_id}")
            _git(self.repo, "push")
        return path
