from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .adapters.git import GitAdapter
from .adapters.postgresql import PostgreSQLAdapter
from .capabilities import CapabilitySnapshot, CapabilityState
from .config import XPConfig
from .project_registry import ProjectRegistry, load_project_profile


@dataclass(frozen=True)
class ReadinessCheck:
    code: str
    level: str  # CLEAR | INFO | WARNING | BLOCKER
    title: str
    detail: str


@dataclass(frozen=True)
class ReadinessReport:
    overall: str  # READY | READY_WITH_LIMITATIONS | NOT_READY
    project_name: str | None
    checks: tuple[ReadinessCheck, ...]


_CAPABILITY_LEVEL_MAP = {
    CapabilityState.AVAILABLE: "CLEAR",
    CapabilityState.NEEDS_ATTENTION: "WARNING",
    CapabilityState.UNAVAILABLE: "BLOCKER",
    CapabilityState.NOT_CHECKED: "INFO",
}


def capability_snapshot_to_check(
    snapshot: CapabilitySnapshot,
) -> ReadinessCheck:
    """Render one AF-03 canonical snapshot as legacy readiness output."""

    code_name = "".join(
        char if char.isalnum() else "_"
        for char in snapshot.capability_id.upper()
    ).strip("_")

    return ReadinessCheck(
        code=f"CAPABILITY_{code_name}",
        level=_CAPABILITY_LEVEL_MAP[snapshot.state],
        title=snapshot.capability_id,
        detail=snapshot.detail,
    )


def _add(checks: list[ReadinessCheck], code: str, level: str, title: str, detail: str) -> None:
    checks.append(ReadinessCheck(code, level, title, detail))


def audit_workstation(
    home: Path,
    *,
    check_database_connection: bool = True,
    project_override=None,
) -> ReadinessReport:
    home = Path(home).expanduser().resolve()
    checks: list[ReadinessCheck] = []
    from .compatibility_audit import find_legacy_upgrade_stray_artifacts

    # Core workstation requirements.
    for command in ("python", "git"):
        if shutil.which(command):
            _add(checks, f"CORE_{command.upper()}", "CLEAR", command, "Tersedia")
        else:
            _add(checks, f"CORE_{command.upper()}", "BLOCKER", command, "Belum tersedia")

    root = home / ".expert-workstation"
    try:
        root.mkdir(parents=True, exist_ok=True)
        writable = os.access(root, os.W_OK)
    except OSError:
        writable = False
    _add(checks, "STATE_STORAGE", "CLEAR" if writable else "BLOCKER", "Penyimpanan XP", "Siap" if writable else "Tidak dapat ditulis")

    legacy_strays = find_legacy_upgrade_stray_artifacts(home)
    if legacy_strays:
        legacy_detail = "REPORT-ONLY: " + ", ".join(
            str(item.path) for item in legacy_strays
        ) + "; XP does not delete these inherited rc18.3 artifacts; cleanup requires explicit user approval"
        _add(
            checks,
            "LEGACY_UPGRADE_STRAY_ARTIFACTS",
            "INFO",
            "Legacy rc18.3 upgrade artifacts",
            legacy_detail,
        )
    else:
        _add(
            checks,
            "LEGACY_UPGRADE_STRAY_ARTIFACTS",
            "CLEAR",
            "Legacy rc18.3 upgrade artifacts",
            "Tidak terdeteksi",
        )
    registry = ProjectRegistry.for_home(home)
    project = project_override or registry.last_active()
    if not project:
        overall = "NOT_READY" if any(c.level == "BLOCKER" for c in checks) else "READY_WITH_LIMITATIONS"
        _add(checks, "PROJECT", "WARNING", "Project aktif", "Belum ada project aktif")
        return ReadinessReport(overall, None, tuple(checks))

    project_name = project.name
    if not project.repo_path:
        _add(checks, "PROJECT_SOURCE", "BLOCKER", "Source project", "Project masih remote-only")
        return ReadinessReport("NOT_READY", project_name, tuple(checks))

    repo = Path(project.repo_path)
    try:
        profile = load_project_profile(repo)
    except Exception as exc:
        _add(checks, "PROJECT_PROFILE", "BLOCKER", "Profile project", f"Tidak valid: {exc}")
        return ReadinessReport("NOT_READY", project_name, tuple(checks))
    _add(checks, "PROJECT_PROFILE", "CLEAR", "Profile project", "Valid")

    compatibility_path = repo / ".xp" / "compatibility.json"
    try:
        compatibility = json.loads(compatibility_path.read_text(encoding="utf-8")) if compatibility_path.exists() else {}
    except Exception as exc:
        _add(checks, "COMPATIBILITY", "BLOCKER", "Compatibility profile", f"Tidak valid: {exc}")
        compatibility = {}

    required = [str(x) for x in compatibility.get("required_commands", [])]
    db_commands = [str(x) for x in compatibility.get("database_commands", [])]
    for command in required:
        level = "CLEAR" if shutil.which(command) else "BLOCKER"
        _add(checks, f"COMMAND_{command.upper()}", level, f"Aplikasi {command}", "Tersedia" if level == "CLEAR" else "Belum tersedia")
    for command in db_commands:
        level = "CLEAR" if shutil.which(command) else "BLOCKER"
        _add(checks, f"COMMAND_{command.upper()}", level, f"Aplikasi {command}", "Tersedia" if level == "CLEAR" else "Belum tersedia")

    try:
        state = GitAdapter(repo).state(fetch=False)
    except Exception as exc:
        _add(checks, "GIT_STATE", "BLOCKER", "Git state", f"Tidak dapat diperiksa: {exc}")
        state = None

    policies_path = repo / ".xp" / "policies.json"
    try:
        policies = json.loads(policies_path.read_text(encoding="utf-8")) if policies_path.exists() else {}
    except Exception as exc:
        _add(checks, "POLICY", "BLOCKER", "Policy project", f"Tidak valid: {exc}")
        policies = {}

    if state is not None:
        protected = {str(x) for x in policies.get("protected_branches", [])}
        allowed_prefixes = tuple(str(x) for x in policies.get("allowed_branch_prefixes", []))
        if state.branch in protected:
            _add(checks, "BRANCH_POLICY", "BLOCKER", "Branch kerja", f"Branch {state.branch} dilindungi")
        elif state.branch and allowed_prefixes and not state.branch.startswith(allowed_prefixes):
            _add(checks, "BRANCH_POLICY", "BLOCKER", "Branch kerja", f"Branch {state.branch} di luar prefix yang diizinkan")
        else:
            if state.branch:
                _add(checks, "BRANCH_POLICY", "CLEAR", "Branch kerja", state.branch)
            else:
                _add(checks, "BRANCH_POLICY", "WARNING", "Branch kerja", "Detached HEAD; XP run akan memblokir sampai checkout branch kerja")
        _add(checks, "WORKING_TREE", "WARNING" if state.dirty else "CLEAR", "Kondisi source", "Ada perubahan lokal" if state.dirty else "Bersih")
        _add(checks, "GIT_REMOTE", "CLEAR" if state.remote else "WARNING", "Git remote", "Tersedia" if state.remote else "Belum ada origin remote")
        if state.remote:
            if state.fetch_checked and state.fetch_ok is False:
                _add(checks, "GIT_SYNC", "WARNING", "Sinkronisasi Git", "Remote belum dapat diverifikasi; periksa jaringan/auth Git")
            elif not state.upstream:
                _add(checks, "GIT_SYNC", "WARNING", "Sinkronisasi Git", "Branch kerja belum memiliki upstream remote")
            elif state.diverged or state.behind:
                detail = f"Remote lebih maju {state.behind} commit" + (f" dan lokal lebih maju {state.ahead} commit" if state.ahead else "")
                _add(checks, "GIT_SYNC", "BLOCKER", "Sinkronisasi Git", detail + "; wajib direkonsiliasi sebelum eksekusi")
            elif state.ahead:
                _add(checks, "GIT_SYNC", "WARNING", "Sinkronisasi Git", f"{state.ahead} commit lokal belum terlindungi di remote")
            else:
                _add(checks, "GIT_SYNC", "CLEAR", "Sinkronisasi Git", "Tidak ada selisih yang terdeteksi dari upstream lokal")

    cfg = XPConfig.for_home(home)
    control_ok = bool(cfg.control_repo and (Path(cfg.control_repo) / ".git").exists())
    _add(checks, "REMOTE_RECOVERY", "CLEAR" if control_ok else "WARNING", "Remote recovery", "Aktif" if control_ok else "Belum dikonfigurasi")
    gh_available = shutil.which("gh") is not None
    if control_ok:
        _add(checks, "GITHUB_CLI", "CLEAR" if gh_available else "INFO", "GitHub CLI", "Tersedia" if gh_available else "Tidak diperlukan untuk workflow lokal saat ini")
    else:
        _add(checks, "GITHUB_CLI", "CLEAR" if gh_available else "WARNING", "GitHub CLI", "Siap untuk aktivasi recovery" if gh_available else "Belum tersedia; dibutuhkan untuk setup recovery GitHub otomatis")

    if profile.database_adapter == "postgresql":
        has_url = bool(os.environ.get("DATABASE_URL"))
        _add(checks, "DATABASE_CREDENTIAL", "CLEAR" if has_url else "WARNING", "Credential database", "Tersedia" if has_url else "Belum dikonfigurasi di perangkat")
        if check_database_connection and has_url and shutil.which("psql"):
            env = PostgreSQLAdapter().environment_status(check_connection=True)
            _add(checks, "DATABASE_CONNECTION", "CLEAR" if env.connection_ok else "WARNING", "Koneksi database", "Terhubung" if env.connection_ok else "Belum dapat dijangkau")
    else:
        _add(checks, "DATABASE", "INFO", "Database", "Tidak digunakan atau belum dideklarasikan")

    deployment = dict(policies.get("deployment") or {})
    if profile.deployment_adapter:
        _add(checks, "PRODUCTION_DEPLOY", "INFO", "Production deploy", f"Adapter: {profile.deployment_adapter}")
    elif deployment.get("production") == "DISABLED":
        _add(checks, "PRODUCTION_DEPLOY", "INFO", "Production deploy", "Sengaja dinonaktifkan sampai mekanisme diverifikasi")
    else:
        _add(checks, "PRODUCTION_DEPLOY", "WARNING", "Production deploy", "Belum dikonfigurasi")

    if any(c.level == "BLOCKER" for c in checks):
        overall = "NOT_READY"
    elif any(c.level == "WARNING" for c in checks):
        overall = "READY_WITH_LIMITATIONS"
    else:
        overall = "READY"
    return ReadinessReport(overall, project_name, tuple(checks))

def audit_project_readiness(repo: Path, *, home: Path | None = None):
    """Additive XP+ project-level readiness API; legacy workstation audit is unchanged."""
    from .project_doctor import ProjectDoctor
    return ProjectDoctor(home).inspect(repo)
