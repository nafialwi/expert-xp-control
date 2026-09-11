from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import XPConfig
from .control import ControlStateManager
from .project_registry import ProjectRegistry
from .redaction import redact_text


class GitHubRecoveryError(RuntimeError):
    pass


class GitHubCLI:
    """Bounded wrapper around GitHub CLI for XP recovery setup only."""

    def __init__(self, binary: str = "gh"):
        self.binary = binary

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def _run(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        if not self.available():
            raise GitHubRecoveryError("GitHub CLI (gh) belum tersedia")
        result = subprocess.run([self.binary, *args], text=True, capture_output=True)
        if check and result.returncode != 0:
            message = redact_text(result.stderr.strip() or result.stdout.strip() or "GitHub CLI command failed")
            raise GitHubRecoveryError(message)
        return result

    def authenticated(self) -> bool:
        try:
            return self._run(["auth", "status"], check=False).returncode == 0
        except GitHubRecoveryError:
            return False

    def login(self) -> None:
        if not self.available():
            raise GitHubRecoveryError("GitHub CLI (gh) belum tersedia")
        result = subprocess.run([self.binary, "auth", "login"])
        if result.returncode != 0:
            raise GitHubRecoveryError("Login GitHub belum berhasil")

    def username(self) -> str:
        if not self.authenticated():
            raise GitHubRecoveryError("GitHub CLI belum login. Jalankan login GitHub lebih dahulu.")
        result = self._run(["api", "user", "--jq", ".login"])
        value = result.stdout.strip()
        if not value:
            raise GitHubRecoveryError("Tidak dapat membaca identitas akun GitHub")
        return value

    def repo_visibility(self, full_name: str) -> str | None:
        result = self._run(["repo", "view", full_name, "--json", "visibility", "--jq", ".visibility"], check=False)
        if result.returncode != 0:
            return None
        return result.stdout.strip().upper() or None

    def ensure_private_repo(self, owner: str, name: str) -> bool:
        full_name = f"{owner}/{name}"
        visibility = self.repo_visibility(full_name)
        if visibility is not None:
            if visibility != "PRIVATE":
                raise GitHubRecoveryError(f"Repository {full_name} harus PRIVATE untuk XP control-state")
            return False
        self._run([
            "api", "-X", "POST", "user/repos",
            "-f", f"name={name}",
            "-F", "private=true",
            "-F", "auto_init=true",
        ])
        return True

    def clone(self, full_name: str, destination: Path) -> None:
        destination = Path(destination)
        result = self._run(["repo", "clone", full_name, str(destination)], check=False)
        if result.returncode != 0:
            raise GitHubRecoveryError(redact_text(result.stderr.strip() or result.stdout.strip() or "Clone control repository gagal"))


@dataclass(frozen=True)
class GitHubRecoverySetupResult:
    owner: str
    repository: str
    path: Path
    created_repository: bool
    restored_existing_state: bool


class GitHubControlRecovery:
    def __init__(self, home: Path, *, client: GitHubCLI | None = None):
        self.home = Path(home).expanduser().resolve()
        self.client = client or GitHubCLI()

    @staticmethod
    def _ensure_local_git_identity(repo: Path) -> None:
        def get(name: str) -> str:
            result = subprocess.run(["git", "config", "--get", name], cwd=repo, text=True, capture_output=True)
            return result.stdout.strip() if result.returncode == 0 else ""
        if not get("user.name"):
            subprocess.run(["git", "config", "user.name", "Expert Workstation"], cwd=repo, check=True)
        if not get("user.email"):
            subprocess.run(["git", "config", "user.email", "xp@local.invalid"], cwd=repo, check=True)

    def setup(self, *, repo_name: str = "expert-xp-control") -> GitHubRecoverySetupResult:
        if not self.client.available():
            raise GitHubRecoveryError("GitHub CLI (gh) belum tersedia")
        if not self.client.authenticated():
            raise GitHubRecoveryError("GitHub CLI belum login")
        owner = self.client.username()
        created = self.client.ensure_private_repo(owner, repo_name)
        full_name = f"{owner}/{repo_name}"
        control_path = self.home / ".expert-workstation" / "control-repo"
        if control_path.exists() and not (control_path / ".git").exists():
            raise GitHubRecoveryError("Folder control-repo sudah ada tetapi bukan Git repository")
        if not control_path.exists():
            control_path.parent.mkdir(parents=True, exist_ok=True)
            self.client.clone(full_name, control_path)
        self._ensure_local_git_identity(control_path)
        XPConfig.for_home(self.home).set_control_repo(control_path)

        snapshot = control_path / "state" / "xp-control-state.json"
        local_has_projects = bool(ProjectRegistry.for_home(self.home).list_projects())
        restored = False
        manager = ControlStateManager(self.home)
        if snapshot.is_file() and not local_has_projects:
            manager.restore(snapshot)
            restored = True
        else:
            manager.sync_to_repo(control_path, push=True)
        return GitHubRecoverySetupResult(owner, full_name, control_path, created, restored)
