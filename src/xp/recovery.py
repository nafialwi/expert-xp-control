from __future__ import annotations

from dataclasses import dataclass

from .journal import Journal
from .models import RunState


@dataclass(frozen=True)
class RecoveryDecision:
    status: str
    operation: str | None
    message: str


class RecoveryEngine:
    SAFE_RETRY_OPERATIONS = {"SOURCE_VERIFY", "BUILD", "TEST", "REMOTE_SAFEPOINT"}
    CRITICAL_OPERATIONS = {"DB_APPLY", "SOURCE_APPLY", "LOCKING"}

    def __init__(self, journal: Journal):
        self.journal = journal

    def inspect(self, run: RunState) -> RecoveryDecision:
        interrupted = self.journal.interrupted_operation()
        if not interrupted:
            return RecoveryDecision("NO_INTERRUPTION", None, "No interrupted operation found.")
        operation = str(interrupted.get("operation"))
        if operation in self.SAFE_RETRY_OPERATIONS:
            return RecoveryDecision("SAFE_RETRY", operation, "Operation is idempotent/safe to rerun.")
        if operation in self.CRITICAL_OPERATIONS:
            return RecoveryDecision(
                "RECOVERY_REQUIRED",
                operation,
                "Critical operation was interrupted; inspect actual project/database state before resuming.",
            )
        return RecoveryDecision("RECOVERY_REQUIRED", operation, "Unknown interrupted operation requires audit.")


class ProjectRecoveryError(RuntimeError):
    pass


class ProjectRecoveryManager:
    """Restore a REMOTE_ONLY project source without guessing project identity.

    Recovery uses the remote URL saved in the sanitized registry and, when an
    active run records one, the work branch saved in the run state. The cloned
    repository must contain matching ``.xp`` project metadata before it is
    promoted back to LOCAL state.
    """

    def __init__(self, home):
        from pathlib import Path
        from .paths import XPPaths
        from .project_registry import ProjectRegistry
        from .state_store import StateStore

        self.home = Path(home).expanduser().resolve()
        self.paths = XPPaths.from_home(self.home)
        self.paths.ensure_runtime_dirs()
        self.registry = ProjectRegistry(self.paths)
        self.store = StateStore(self.paths)

    def _latest_run(self, project_id: str):
        candidates = []
        if not self.paths.runs.exists():
            return None
        for state_file in self.paths.runs.glob("*/state.json"):
            try:
                state = self.store.load(state_file.parent.name)
            except Exception:
                continue
            if state.project_id == project_id:
                candidates.append((state_file.stat().st_mtime, state))
        return max(candidates, key=lambda item: item[0])[1] if candidates else None

    def recover(self, project_id: str, *, destination=None):
        import subprocess
        from pathlib import Path
        from .project_registry import load_project_profile

        projects = {item.project_id: item for item in self.registry.list_projects()}
        summary = projects.get(project_id)
        if summary is None:
            raise ProjectRecoveryError(f"Unknown project: {project_id}")
        if not summary.remote_url:
            raise ProjectRecoveryError("Project has no recoverable Git remote URL")
        if destination is None:
            destination = self.home / "projects" / project_id
        destination = Path(destination).expanduser().resolve()
        if destination.exists():
            raise ProjectRecoveryError(f"Recovery destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)

        run = self._latest_run(project_id)
        branch = str(run.metadata.get("branch")) if run and run.metadata.get("branch") else None
        cmd = ["git", "clone"]
        if branch:
            cmd += ["--branch", branch, "--single-branch"]
        cmd += [summary.remote_url, str(destination)]
        result = subprocess.run(cmd, text=True, capture_output=True)
        if result.returncode != 0:
            import shutil
            shutil.rmtree(destination, ignore_errors=True)
            raise ProjectRecoveryError(result.stderr.strip() or result.stdout.strip() or "git clone failed")
        try:
            profile = load_project_profile(destination)
            if profile.project_id != project_id:
                raise ProjectRecoveryError(
                    f"Recovered source identity mismatch: expected {project_id}, got {profile.project_id}"
                )
            self.registry.register(profile, destination)
        except Exception:
            import shutil
            shutil.rmtree(destination, ignore_errors=True)
            raise
        return destination
