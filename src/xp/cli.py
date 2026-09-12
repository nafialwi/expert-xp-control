from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .autopilot import AutopilotController
from .adapters.postgresql import PostgreSQLAdapter
from .adapters.git import GitAdapter
from .inbox import scan_inbox
from .models import RunState
from .packages import RunContext
from .paths import XPPaths
from .project_registry import ProjectRegistry, load_project_profile
from .recovery import RecoveryEngine, ProjectRecoveryManager
from .journal import Journal
from .control import ControlStateManager
from .config import XPConfig
from .onboarding import ProjectOnboarder, OnboardingError
from .state_store import StateStore
from .handoff import HandoffBuilder, HandoffContext
from .redaction import sanitize_mapping
from .ui import clear_screen, header, wait_for_enter, human_path
from .readiness import audit_workstation
from .workflow import PRIMARY_SEQUENCE
from .github_recovery import GitHubCLI, GitHubControlRecovery, GitHubRecoveryError


def _list_locked_milestones(project_id: str) -> list[str]:
    checkpoints_dir = _paths().checkpoints / project_id
    if not checkpoints_dir.exists():
        return []
    milestones = []
    for run_dir in checkpoints_dir.iterdir():
        if not run_dir.is_dir():
            continue
        state_file = run_dir / "CHECKPOINT_STATE.json"
        if not state_file.exists():
            continue
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            milestone = data.get("milestone")
            if milestone:
                milestones.append(milestone)
        except Exception:
            continue
    return sorted(set(milestones))


def _read_roadmap_progress(repo_path: Path) -> tuple[float, str] | None:
    roadmap_file = repo_path / "docs" / "checkpoints" / "ROADMAP_PROGRESS.md"
    if not roadmap_file.exists():
        return None
    try:
        content = roadmap_file.read_text(encoding="utf-8")
        import re
        match = re.search(r'Whole-project earned progress: `(\d+\.?\d*)%`', content)
        if match:
            return float(match.group(1)), str(roadmap_file)
    except Exception:
        pass
    return None




def _roadmap_buckets(repo: Path):
    path = Path(repo) / "docs" / "checkpoints" / "ROADMAP_PROGRESS.md"
    if not path.is_file():
        return None, None
    buckets = []
    current = None
    overall = None
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("### "):
            current = s[4:].strip()
        elif current and s.startswith("- Completion:"):
            digits = "".join(ch for ch in s if ch.isdigit())
            buckets.append((current, int(digits) if digits else 0))
            current = None
        elif s.startswith("- Whole-project earned progress:"):
            tail = "".join(ch for ch in s.split(":")[-1] if ch.isdigit() or ch == ".")
            overall = tail
    return buckets, overall
def _home() -> Path:
    return Path(os.environ.get("XP_USER_HOME", str(Path.home()))).expanduser().resolve()


def _paths() -> XPPaths:
    return XPPaths.from_home(_home())


def _latest_run(paths: XPPaths, project_id: str | None = None, *, include_terminal: bool = True) -> RunState | None:
    if not paths.runs.exists():
        return None
    states: list[tuple[float, RunState]] = []
    store = StateStore(paths)
    for item in paths.runs.iterdir():
        state_file = item / "state.json"
        if not state_file.is_file():
            continue
        try:
            state = store.load(item.name)
        except Exception:
            continue
        if project_id and state.project_id != project_id:
            continue
        if not include_terminal and state.stage in {"LOCKED_LOCAL", "LOCKED_REMOTE"}:
            continue
        states.append((state_file.stat().st_mtime, state))
    return max(states, key=lambda x: x[0])[1] if states else None


def _status() -> int:
    registry = ProjectRegistry.for_home(_home())
    projects = registry.list_projects()
    clear_screen()
    header()
    print("STATUS WORKSTATION")
    print()
    if not projects:
        print("Belum ada project yang terdaftar.")
        print("Engine XP siap digunakan untuk menambah atau memulihkan project.")
        return 0
    last = registry.last_active() or projects[0]
    run = _latest_run(_paths(), last.project_id)
    print(f"Project       : {last.name}")
    print(f"Ketersediaan  : {'Lokal' if last.repo_path else 'Remote only'}")
    if run:
        print(f"Pekerjaan     : {run.milestone or run.run_id}")
        print(f"Tahap         : {run.stage}")
    else:
        print("Pekerjaan     : Tidak ada pekerjaan aktif")
    return 0


def _self_test() -> int:
    paths = _paths()
    paths.ensure_runtime_dirs()
    checks = {
        "Python": sys.version_info >= (3, 10),
        "Git": shutil.which("git") is not None,
        "Penyimpanan XP": os.access(paths.root, os.W_OK),
        "PostgreSQL Client": shutil.which("psql") is not None,
    }
    clear_screen()
    header()
    print("CEK KESEHATAN XP")
    print()
    print("PERANGKAT")
    for name, ok in checks.items():
        symbol = "✓" if ok else "?"
        status = "Siap" if ok else "Belum tersedia"
        print(f"{symbol} {name:<20} {status}")

    registry = ProjectRegistry.for_home(_home())
    project = registry.last_active()
    print()
    print("KONEKSI PROJECT")
    if not project:
        print("- Belum ada project aktif")
    elif not project.repo_path:
        print(f"- {project.name}: source masih remote only")
    else:
        try:
            profile = load_project_profile(Path(project.repo_path))
        except Exception:
            print(f"? {project.name}: profile project belum dapat dibaca")
        else:
            if profile.database_adapter == "postgresql":
                if not checks["PostgreSQL Client"]:
                    print("? Database: PostgreSQL Client belum tersedia")
                elif not os.environ.get("DATABASE_URL"):
                    print("? Database: credential project belum dikonfigurasi")
                else:
                    env = PostgreSQLAdapter().environment_status(check_connection=True)
                    print("✓ Database: terhubung" if env.connection_ok else "? Database: belum dapat dijangkau")
            else:
                print("- Database: project tidak memakai PostgreSQL")

    critical = checks["Python"] and checks["Git"] and checks["Penyimpanan XP"]
    print()
    print("CORE: CLEAR" if critical else "CORE: ERROR")
    if not checks["PostgreSQL Client"]:
        print("Catatan: PostgreSQL Client hanya wajib untuk project yang memerlukannya.")
    return 0 if critical else 2



def _render_readiness(report) -> None:
    clear_screen()
    header()
    print("AUDIT KESIAPAN")
    print()
    print(f"Status  : {report.overall}")
    print(f"Project : {report.project_name or 'Belum ada project aktif'}")
    print()
    symbols = {"CLEAR": "✓", "INFO": "-", "WARNING": "⚠", "BLOCKER": "✗"}
    for check in report.checks:
        print(f"{symbols.get(check.level, '?')} {check.title}: {check.detail}")
    print()
    if report.overall == "READY":
        print("XP siap menjalankan workflow yang sudah dikonfigurasi untuk project aktif.")
    elif report.overall == "READY_WITH_LIMITATIONS":
        print("XP dapat dipakai, tetapi ada perlindungan/koneksi yang belum lengkap.")
    else:
        print("XP belum boleh menjalankan pekerjaan project sampai blocker diselesaikan.")


def _audit() -> int:
    report = audit_workstation(_home(), check_database_connection=True)
    _render_readiness(report)
    return 0


def _protect_source_remote(project) -> int:
    if not project.repo_path:
        print("Source project belum tersedia lokal.")
        return 2
    repo = Path(project.repo_path)
    try:
        policy_path = repo / ".xp" / "policies.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8")) if policy_path.exists() else {}
        git = GitAdapter(repo)
        state = git.state(fetch=True)
    except Exception as exc:
        print(f"Source belum dapat diperiksa: {exc}")
        return 2
    protected = set(str(x) for x in policy.get("protected_branches", ["main", "master"]))
    allowed = tuple(str(x) for x in policy.get("allowed_branch_prefixes", ["work/", "xp/recovery/"]))
    if not state.branch:
        print("Source tidak dipush: repository berada pada detached HEAD.")
        return 2
    if state.branch in protected or (allowed and not state.branch.startswith(allowed)):
        print(f"Source tidak dipush: branch {state.branch} tidak memenuhi policy XP.")
        return 2
    if state.dirty:
        print("Source tidak dipush otomatis karena masih ada perubahan lokal yang belum diaudit.")
        return 2
    if state.diverged or state.behind:
        print("Source tidak dipush: remote lebih maju/diverged dan harus direkonsiliasi lebih dahulu.")
        return 2
    if not state.remote:
        print("Source belum memiliki origin remote.")
        return 2
    if state.upstream and state.ahead <= 0:
        print("Source sudah terlindungi di remote; tidak ada commit lokal yang tertinggal.")
        return 0
    print("LINDUNGI SOURCE KE REMOTE")
    print()
    print(f"Branch : {state.branch}")
    if state.upstream:
        print(f"Commit lokal belum terlindungi: {state.ahead}")
    else:
        print("Upstream remote belum terpasang untuk branch ini.")
    print()
    print("[1] Push branch ini ke origin")
    print("[0] Batal")
    try:
        choice = input("Pilih: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 0
    if choice != "1":
        return 0
    try:
        git.push_current_branch(remote="origin")
        after = git.state(fetch=True)
    except Exception as exc:
        print(f"Push belum berhasil: {exc}")
        return 2
    if after.behind or after.diverged or after.ahead:
        print("Push selesai tetapi sinkronisasi belum clear; audit ulang diperlukan.")
        return 2
    print("✓ Source sudah terlindungi di remote.")
    return 0


def _configure_database_session(project) -> int:
    if not project.repo_path:
        print("Project belum tersedia lokal.")
        return 2
    try:
        profile = load_project_profile(Path(project.repo_path))
    except Exception as exc:
        print(f"Profile project belum dapat dibaca: {exc}")
        return 2
    if profile.database_adapter != "postgresql":
        print("Project aktif tidak menggunakan PostgreSQL.")
        return 0
    print("HUBUNGKAN DATABASE — SESI INI")
    print()
    print("XP tidak menyimpan credential database ke repository, log, handoff, atau recovery remote.")
    print("Credential ini hanya hidup selama proses XP ini berjalan.")
    try:
        value = getpass.getpass("Tempel DATABASE_URL PostgreSQL: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 0
    if not value:
        print("Credential tidak diubah.")
        return 0
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = value
    status = PostgreSQLAdapter().environment_status(check_connection=True)
    if not status.connection_ok:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        print("Database belum dapat dihubungi. Credential tidak dipertahankan pada sesi XP.")
        if status.message:
            from .redaction import redact_text
            print(f"Detail aman: {redact_text(status.message, known_secrets=[value])}")
        return 2
    print("✓ Database terhubung.")
    print("Credential aktif untuk sesi XP ini dan tidak disimpan ke disk oleh XP.")
    return 0


def _readiness_center(project) -> int:
    while True:
        report = audit_workstation(_home(), check_database_connection=True)
        _render_readiness(report)
        print()
        print("TINDAKAN KESIAPAN")
        print()
        print("[1] Lindungi source ke remote")
        print("[2] Recovery & perlindungan")
        print("[3] Hubungkan database untuk sesi ini")
        print("[4] Audit ulang")
        print("[0] Kembali")
        try:
            choice = input("Pilih: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice == "0":
            return 0
        if choice == "1":
            _protect_source_remote(project)
            wait_for_enter()
            continue
        if choice == "2":
            _recovery_menu()
            continue
        if choice == "3":
            _configure_database_session(project)
            wait_for_enter()
            continue
        if choice == "4":
            continue
        print("Pilihan tidak tersedia. Gunakan angka 0–4.")
        wait_for_enter()


def _project_search_roots(home: Path) -> list[Path]:
    candidates = [
        home / "projects",
        home / "WORKSTATION" / "projects",
        home / "workstation" / "projects",
        home / "workspace",
        home / "Workspace",
        home / "repos",
        home / "src",
    ]
    try:
        children = list(home.iterdir())
    except OSError:
        children = []
    for child in children:
        if not child.is_dir() or child.name.startswith(".") or child.name in {"storage", "node_modules"}:
            continue
        if (child / ".git").exists():
            candidates.append(child)
        nested_projects = child / "projects"
        if nested_projects.is_dir():
            candidates.append(nested_projects)
    roots: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            roots.append(resolved)
    return roots


def _discover_git_repositories(home: Path) -> list[Path]:
    repositories: list[Path] = []
    for search_root in _project_search_roots(home):
        if (search_root / ".git").exists():
            repositories.append(search_root.resolve())
            continue
        for current, dirs, _files in os.walk(search_root):
            path = Path(current)
            depth = len(path.relative_to(search_root).parts)
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"node_modules", "storage"}]
            if (path / ".git").exists():
                repositories.append(path.resolve())
                dirs[:] = []
                continue
            if depth >= 2:
                dirs[:] = []
    return sorted(set(repositories))


def _bundled_profile_packages(home: Path) -> list[Path]:
    root = home / ".expert-workstation"
    active_file = root / "active-version"
    candidates: list[Path] = []
    if active_file.is_file():
        version = active_file.read_text(encoding="utf-8").strip()
        package_dir = root / "versions" / version / "packages"
        if package_dir.is_dir():
            candidates.extend(sorted(package_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True))
    for package_dir in [home / "storage" / "downloads" / "Expert", home / "storage" / "downloads"]:
        if package_dir.is_dir():
            candidates.extend(sorted(package_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True))
    unique: list[Path] = []
    seen: set[Path] = set()
    for item in candidates:
        resolved = item.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def _onboard_from_home_menu() -> int:
    home = _home()
    onboarder = ProjectOnboarder(home)
    repos = _discover_git_repositories(home)
    packages = _bundled_profile_packages(home)

    # Candidate shape: (repo, package-or-none, display name, profile_already_present)
    by_repo: dict[Path, tuple[Path, Path | None, str, bool]] = {}
    for repo in repos:
        try:
            profile = load_project_profile(repo)
        except Exception:
            continue
        by_repo[repo] = (repo, None, profile.name, True)

    for package in packages:
        for repo in repos:
            if repo in by_repo:
                continue
            try:
                manifest = onboarder.validate_target(repo, package)
            except (OnboardingError, OSError, ValueError):
                continue
            by_repo[repo] = (repo, package, manifest.project_name, False)

    matches = list(by_repo.values())
    clear_screen()
    header()
    print("TAMBAH PROJECT")
    print()
    if not matches:
        print("Belum ditemukan project yang dapat ditambahkan otomatis.")
        print("XP tidak mengubah file apa pun.")
        print()
        print("Project existing tetap dapat diaudit/import pada tahap berikutnya melalui GPT handoff.")
        return 0

    shown = matches[:4]
    print(f"{len(shown)} project ditemukan.")
    print()
    for index, (_repo, _package, name, existing) in enumerate(shown, 1):
        marker = " — Profile XP sudah ada" if existing else ""
        print(f"[{index}] {name}{marker}")
    print("[0] Batal")
    try:
        selected = input("Pilih project: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 0
    if selected == "0":
        print("Tidak ada perubahan yang dilakukan.")
        return 0
    if not selected.isdigit() or not (1 <= int(selected) <= len(shown)):
        print("Pilihan tidak tersedia. Tidak ada perubahan yang dilakukan.")
        return 0

    repo, package, _name, existing = shown[int(selected) - 1]
    clear_screen()
    header()
    print("MENYIAPKAN PROJECT")
    print()
    try:
        if existing:
            profile = load_project_profile(repo)
            ProjectRegistry.for_home(home).register(profile, repo)
            print("✓ Source dikenali")
            print("✓ Profile XP sudah ada")
            print("✓ Project didaftarkan")
            print("✓ Tidak ada source business logic yang diubah")
        else:
            assert package is not None
            print("✓ Source dan anchor canonical cocok")
            profile = onboarder.apply(repo, package)
            print("✓ Profile XP dipasang")
            print("✓ Safepoint profile dibuat")
            print("✓ Project didaftarkan")
    except Exception as exc:
        print("✗ PROJECT BELUM DITAMBAHKAN")
        print()
        print(f"Alasan: {exc}")
        print("XP berhenti tanpa melanjutkan ke pekerjaan project.")
        return 2

    print()
    print("PROJECT BERHASIL DITAMBAHKAN")
    checkpoint = profile.metadata.get("current_canonical_milestone")
    if checkpoint:
        print(f"Checkpoint dikenali: {checkpoint}")

    print()
    print("XP menyiapkan pengenalan awal untuk GPT agar pekerjaan berikutnya memakai source yang tepat.")
    try:
        _kind, artifact = _build_handoff(str(repo))
    except Exception as exc:
        print("? Project sudah siap, tetapi Bootstrap GPT handoff belum dapat dibuat.")
        print(f"  Alasan: {exc}")
        print("  Handoff dapat dibuat lagi dari menu GPT baru / handoff.")
        return 0
    print()
    print("File untuk GPT:")
    print(artifact.name)
    print(f"Lokasi: {human_path(artifact.parent)}")
    return 0


def _recovery_candidates(home: Path) -> list[Path]:
    values: list[Path] = []
    for root in (home / "storage" / "downloads" / "Expert", home / "storage" / "downloads"):
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("control_version") == 1:
                values.append(path)
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in values:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique[:4]


def _recovery_status() -> None:
    cfg = XPConfig.for_home(_home())
    print("STATUS PERLINDUNGAN RECOVERY")
    print()
    if cfg.control_repo and (Path(cfg.control_repo) / ".git").exists():
        print("✓ Control repository terkonfigurasi")
        print("  Remote state dapat disinkronkan oleh workflow XP.")
    else:
        print("⚠ Remote recovery belum aktif")
        print("  XP lokal tetap dapat dipakai.")
        print("  Jika ponsel hilang sebelum remote recovery diaktifkan, state lokal XP dapat ikut hilang.")


def _setup_github_recovery() -> None:
    clear_screen()
    header()
    print("RECOVERY GITHUB")
    print()
    cli = GitHubCLI()
    if not cli.available():
        print("GitHub CLI belum tersedia di perangkat ini.")
        print("XP tidak memasang aplikasi sistem secara diam-diam.")
        print("Aplikasi yang dibutuhkan untuk fitur ini: gh (GitHub CLI).")
        return
    if not cli.authenticated():
        print("GitHub CLI tersedia tetapi belum login.")
        print()
        print("[1] Mulai login GitHub")
        print("[0] Batal")
        try:
            choice = input("Pilih: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if choice != "1":
            return
        try:
            cli.login()
        except GitHubRecoveryError as exc:
            print(f"Login belum berhasil: {exc}")
            return
    print("Menyiapkan private recovery repository...")
    try:
        result = GitHubControlRecovery(_home(), client=cli).setup()
    except Exception as exc:
        print(f"Recovery GitHub belum berhasil: {exc}")
        return
    print("✓ GitHub terhubung")
    print(f"✓ Control repository PRIVATE: {result.repository}")
    if result.restored_existing_state:
        print("✓ State workstation lama dipulihkan")
    else:
        print("✓ State workstation saat ini diamankan ke GitHub")
    print("Remote recovery: AKTIF")


def _recovery_menu() -> int:
    while True:
        clear_screen()
        header()
        print("PULIHKAN WORKSTATION")
        print()
        print("[1] Aktifkan / pulihkan dari GitHub")
        print("[2] Gunakan file recovery")
        print("[3] Pulihkan project dari remote")
        print("[4] Status perlindungan recovery")
        print("[0] Kembali")
        try:
            choice = input("Pilih: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice == "0":
            return 0
        if choice == "1":
            _setup_github_recovery()
            wait_for_enter()
            continue
        if choice == "2":
            candidates = _recovery_candidates(_home())
            clear_screen()
            header()
            print("FILE RECOVERY")
            print()
            if not candidates:
                print("Belum ada file recovery XP yang ditemukan di Download/Expert.")
                wait_for_enter()
                continue
            for index, path in enumerate(candidates, 1):
                print(f"[{index}] {path.name}")
            print("[0] Batal")
            selected = input("Pilih file: ").strip()
            if selected.isdigit() and 1 <= int(selected) <= len(candidates):
                try:
                    ControlStateManager(_home()).restore(candidates[int(selected) - 1])
                except Exception as exc:
                    print(f"Recovery belum berhasil: {exc}")
                else:
                    print("Workstation berhasil memuat control-state recovery.")
                wait_for_enter()
            continue
        if choice == "3":
            registry = ProjectRegistry.for_home(_home())
            remote = [p for p in registry.list_projects() if not p.repo_path and p.remote_url]
            clear_screen()
            header()
            print("PULIHKAN PROJECT DARI REMOTE")
            print()
            if not remote:
                print("Belum ada project remote-only yang siap dipulihkan.")
                wait_for_enter()
                continue
            for index, project in enumerate(remote, 1):
                print(f"[{index}] {project.name}")
            print("[0] Batal")
            selected = input("Pilih project: ").strip()
            if selected.isdigit() and 1 <= int(selected) <= len(remote):
                chosen = remote[int(selected) - 1]
                try:
                    recovered = ProjectRecoveryManager(_home()).recover(chosen.project_id)
                except Exception as exc:
                    print(f"Project belum berhasil dipulihkan: {exc}")
                else:
                    print(f"Project berhasil dipulihkan: {chosen.name}")
                    print(f"Lokasi lokal: {recovered.name}")
                wait_for_enter()
            continue
        if choice == "4":
            clear_screen()
            header()
            _recovery_status()
            wait_for_enter()
            continue
        print("Pilihan tidak tersedia. Gunakan angka 0–4.")
        wait_for_enter()

def _about() -> None:
    clear_screen()
    header()
    print("TENTANG")
    print()
    print("Expert Workstation adalah workstation project universal berbasis terminal.")
    print("Command utama: xp")
    print()
    print("Peran:")
    print("- Anda: tujuan, keputusan, QA, dan Final Lock.")
    print("- GPT: desain, coding, audit, dan paket remediation/work.")
    print("- XP: workflow, eksekusi aman, verifikasi, recovery, dan evidence.")
    print()
    print(f"Versi engine: {__version__}")


def _project_card(project, run: RunState | None) -> None:
    profile = None
    if project.repo_path:
        try:
            profile = load_project_profile(Path(project.repo_path))
        except Exception:
            profile = None
    cfg = XPConfig.for_home(_home())
    recovery_active = bool(cfg.control_repo and (Path(cfg.control_repo) / ".git").exists())
    
    branch = "—"
    if project.repo_path:
        try:
            from .adapters.git import GitAdapter
            git_state = GitAdapter(Path(project.repo_path)).state(fetch=False)
            branch = git_state.branch or "—"
        except Exception:
            pass
    print(f"{project.name} · {branch}")
    
    buckets, overall = _roadmap_buckets(Path(project.repo_path)) if project.repo_path else (None, None)
    locked = _list_locked_milestones(project.project_id)
    src_label = "✓"
    if project.repo_path:
        try:
            from .adapters.git import GitAdapter
            git_state = GitAdapter(Path(project.repo_path)).state(fetch=False)
            src_label = "⚠" if git_state.dirty else "✓"
        except Exception:
            src_label = "?"
    db_label = "?"
    rec_label = "✓" if recovery_active else "⚠"
    
    if buckets:
        done = sum(1 for _name, p in buckets if p >= 100)
        total = f"{overall}%" if overall else "-"
        print(f"ROADMAP {total} ({done}/{len(buckets)}) · Lock XP: {len(locked)} · Source {src_label} · DB {db_label} · Rec {rec_label}")
    else:
        print(f"Lock XP: {len(locked)} · Source {src_label} · DB {db_label} · Rec {rec_label}")
    
    if buckets:
        done_buckets = [(n, p) for n, p in buckets if p >= 100]
        not_done = [(n, p) for n, p in buckets if p < 100]
        
        if done_buckets:
            def short_name(n):
                s = n.split("—")[0].strip()
                if "/" in s:
                    s = s.split("/")[0].strip()
                return s
            short_names = [short_name(n) for n, _ in done_buckets]
            print(f"Sudah: {' · '.join(short_names)}")
        
        if not_done:
            print("Belum:")
            for idx, (name, pct) in enumerate(not_done):
                mark = "→" if idx == 0 else "[ ]"
                print(f"{mark}  {name}")
    
    if run:
        stage = run.stage
        if stage in {"LOCKED_LOCAL", "LOCKED_REMOTE"}:
            pct = 100
        elif stage in {"HUMAN_QA", "READY_TO_LOCK"}:
            pct = 75
        elif stage == "WAITING_GPT":
            pct = 0
        else:
            pct = 50
        print(f"Pekerjaan: {run.milestone or run.run_id} — {stage} ({pct}%)")
    else:
        print("Pekerjaan: Belum ada")
def _show_autopilot_result(result) -> None:
    print()
    print(f"Status : {result.status}")
    print(f"Tahap  : {result.stage}")
    print(result.message)
    if result.handoff:
        print()
        print("File untuk GPT:")
        print(result.handoff.name)
        print(f"Lokasi: {human_path(result.handoff.parent)}")


def _qa_steps_for_run(run: RunState) -> tuple[str, ...]:
    package_value = str(run.metadata.get("package", ""))
    if package_value:
        try:
            from .packages import inspect_package
            manifest = inspect_package(Path(package_value))
            if manifest.human_qa:
                return manifest.human_qa
        except Exception:
            pass
    return (
        "Uji fungsi yang berubah sesuai tujuan pekerjaan.",
        "Refresh / buka ulang bagian yang diuji dan pastikan hasil tetap benar.",
        "Pastikan fungsi lama yang berkaitan masih bekerja normal.",
    )


def _database_change_summary(repo: Path, run: RunState) -> tuple[int, tuple[str, ...]]:
    package_value = str(run.metadata.get("package", ""))
    if not package_value:
        return 0, ()
    try:
        from .packages import inspect_package
        from .adapters.postgresql import classify_sql
        manifest = inspect_package(Path(package_value))
    except Exception:
        return 0, ()
    classes: list[str] = []
    count = 0
    for op in manifest.operations:
        if op.get("type") != "APPLY_DB_MIGRATION":
            continue
        count += 1
        path = (repo / str(op.get("path", ""))).resolve()
        try:
            if repo == path or repo in path.parents:
                classes.append(classify_sql(path.read_text(encoding="utf-8")))
        except Exception:
            classes.append("BELUM_DIKLASIFIKASI")
    return count, tuple(classes)


def _continue_active_project(project, run: RunState) -> int:
    if not project.repo_path:
        print("Project masih remote-only. Gunakan menu recovery untuk memulihkan source lokal.")
        return 0
    repo = Path(project.repo_path)
    controller = AutopilotController(_home())

    if run.stage == "DB_APPROVAL_REQUIRED":
        clear_screen()
        header()
        print("PERSETUJUAN DATABASE")
        print()
        print(f"Pekerjaan: {run.milestone or run.run_id}")
        count, classes = _database_change_summary(repo, run)
        print(f"Migration yang akan diterapkan: {count}")
        if classes:
            print(f"Klasifikasi: {', '.join(classes)}")
        print()
        print("XP hanya akan melanjutkan migration yang lolos policy keselamatan dan regression test.")
        print("Tidak akan merge ke main.")
        print("Tidak akan deploy production.")
        print()
        print("[1] Lanjutkan perubahan database")
        print("[2] Tunda pekerjaan")
        print("[3] Lihat status / audit")
        print("[0] Kembali")
        try:
            choice = input("Pilih: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice == "1":
            result = controller.continue_database(repo, run.run_id, approved=True)
            _show_autopilot_result(result)
            return 0
        if choice == "2":
            result = controller.continue_database(repo, run.run_id, approved=False)
            _show_autopilot_result(result)
            return 0
        if choice == "3":
            _audit()
        return 0

    if run.stage == "HUMAN_QA":
        clear_screen()
        header()
        print("QA MANUSIA")
        print()
        print(f"Pekerjaan: {run.milestone or run.run_id}")
        print("Automated gate sudah berhenti di titik yang membutuhkan pemeriksaan manusia.")
        print()
        print("Yang perlu Anda coba:")
        for index, step in enumerate(_qa_steps_for_run(run), 1):
            print(f"{index}. {step}")
        print()
        print("[1] QA CLEAR")
        print("[2] ADA MASALAH")
        print("[3] Belum selesai / tunda")
        print("[0] Kembali")
        try:
            choice = input("Pilih: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice == "1":
            result = controller.record_human_qa(repo, run.run_id, clear=True, notes="QA manusia clear melalui menu XP")
            _show_autopilot_result(result)
            return 0
        if choice == "2":
            try:
                notes = input("Tuliskan masalah yang Anda lihat: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not notes:
                print("Masalah belum dicatat karena keterangannya kosong.")
                return 0
            print(f"Masalah dicatat: {notes}")
            result = controller.record_human_qa(repo, run.run_id, clear=False, notes=notes)
            _show_autopilot_result(result)
            return 0
        return 0

    if run.stage == "READY_TO_LOCK":
        clear_screen()
        header()
        print("FINAL LOCK")
        print()
        print(f"Pekerjaan: {run.milestone or run.run_id}")
        print("Semua gate sebelumnya telah mencapai titik siap dikunci.")
        print()
        print("Jika disetujui, XP akan:")
        print("✓ menjalankan final verification")
        print("✓ mencatat Human QA")
        print("✓ membuat commit/checkpoint/source archive + SHA")
        print("✓ mengamankan work branch sesuai policy remote jika tersedia")
        print()
        print("Tidak akan merge ke main.")
        print("Tidak akan deploy production.")
        print()
        print("[1] FINAL LOCK")
        print("[2] Belum / kembali")
        try:
            choice = input("Pilih: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice == "1":
            result = controller.final_lock(repo, run.run_id, approved=True)
            _show_autopilot_result(result)
        return 0

    if run.stage == "WAITING_GPT":
        clear_screen()
        header()
        print("MENUNGGU HASIL GPT")
        print()
        print("XP menghentikan pekerjaan pada titik aman karena diperlukan audit/remediation GPT.")
        print("Setelah file hasil GPT selesai diunduh, pilih 'Scan hasil GPT terbaru' dari Home.")
        handoff = run.metadata.get("handoff") or run.metadata.get("handoff_path")
        if handoff:
            print()
            print(f"Handoff terakhir: {Path(str(handoff)).name}")
        return 0

    result = controller.resume(repo, run.run_id)
    _show_autopilot_result(result)
    # A safe resume can intentionally restore a human gate. Render that gate
    # on the next Home interaction rather than executing it implicitly.
    return 0


def _home_screen() -> int:
    while True:
        registry = ProjectRegistry.for_home(_home())
        projects = registry.list_projects()
        clear_screen()
        header()
        if not projects:
            print("BELUM ADA PROJECT")
            print()
            print("[1] Tambah project")
            print("[2] Pulihkan workstation")
            print("[3] Cek kesehatan XP")
            print("[4] Tentang")
            print("[0] Keluar")
            try:
                choice = input("Pilih: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if choice == "0":
                return 0
            if choice == "1":
                _onboard_from_home_menu()
                wait_for_enter()
                continue
            if choice == "2":
                _recovery_menu()
                continue
            if choice == "3":
                _self_test()
                wait_for_enter()
                continue
            if choice == "4":
                _about()
                wait_for_enter()
                continue
            print("Pilihan tidak tersedia pada layar ini. Gunakan angka 0–4.")
            wait_for_enter()
            continue

        last = registry.last_active() or projects[0]
        run = _latest_run(_paths(), last.project_id)
        active = _latest_run(_paths(), last.project_id, include_terminal=False)
        _project_card(last, run)
        print()
        print("[1] Lanjutkan dari posisi terakhir")
        print("[2] Scan hasil GPT terbaru")
        print("[3] Pilih project lain")
        print("[4] GPT baru / handoff")
        print("[5] Status & audit")
        print("[0] Keluar")
        try:
            choice = input("Pilih: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice == "0":
            return 0
        if choice == "1":
            if not last.repo_path:
                print("Project masih remote-only. Gunakan menu recovery untuk memulihkan source lokal.")
            elif not active:
                print("Belum ada pekerjaan aktif.")
                print("Jika Anda sudah mengunduh paket dari GPT, pilih 'Scan hasil GPT terbaru'.")
            else:
                _continue_active_project(last, active)
            wait_for_enter()
            continue
        if choice == "2":
            _scan_for_last(last, active)
            wait_for_enter()
            continue
        if choice == "3":
            clear_screen()
            header()
            print("PILIH PROJECT")
            print()
            for index, project in enumerate(projects, 1):
                suffix = " — remote only" if not project.repo_path else ""
                print(f"[{index}] {project.name}{suffix}")
            print("[0] Batal")
            try:
                selected = input("Pilih project: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if selected.isdigit() and 1 <= int(selected) <= len(projects):
                chosen = projects[int(selected) - 1]
                ProjectRegistry.for_home(_home()).activate(chosen.project_id)
                print(f"Project aktif: {chosen.name}")
                wait_for_enter()
            continue
        if choice == "4":
            if not last.repo_path:
                print("Project belum tersedia lokal; pulihkan source dahulu sebelum membuat handoff lengkap.")
            else:
                _make_handoff(last.repo_path)
            wait_for_enter()
            continue
        if choice == "5":
            _readiness_center(last)
            continue
        print("Pilihan tidak tersedia pada layar ini. Gunakan angka 0–5.")
        wait_for_enter()

def _scan_for_last(project, run: RunState | None) -> int:
    if not project.repo_path:
        print("Project belum tersedia lokal; pemulihan repository diperlukan dahulu.")
        return 0
    repo = Path(project.repo_path)
    try:
        profile = load_project_profile(repo)
    except Exception as exc:
        print(f"Profile project belum siap: {exc}")
        return 2
    from .adapters.git import GitAdapter
    try:
        fingerprint = GitAdapter(repo).working_fingerprint()
    except Exception:
        fingerprint = "unknown"
    context = RunContext(
        project_id=profile.project_id,
        stage=run.stage if run else "IDLE",
        base_fingerprint=fingerprint,
        run_id=run.run_id if run else None,
        incident_id=(run.metadata.get("incident_id") if run else None),
        incident_challenge=(run.metadata.get("incident_challenge") if run else None),
    )
    downloads = _home() / "storage" / "downloads"
    expert = downloads / "Expert"
    candidates = scan_inbox([expert, downloads], context, limit=4)
    if not candidates:
        print("Tidak ada paket XP kompatibel yang ditemukan.")
        return 0
    print("PAKET XP TERBARU")
    for index, item in enumerate(candidates, 1):
        mark = "★" if item.exact_match else " "
        print(f"[{index}] {mark} {item.manifest.package_type} — {item.manifest.milestone or '-'}")
        print(f"    {item.compatibility_reason}")
    print("\nXP tidak menjalankan file hanya karena terbaru. Pilih paket yang ingin digunakan.")
    selected = input("Pilih paket (0 batal): ").strip()
    if not selected.isdigit() or not (1 <= int(selected) <= len(candidates)):
        return 0
    chosen = candidates[int(selected) - 1]
    if not chosen.exact_match:
        print("Paket tidak cocok persis dengan state aktif. XP tidak menjalankannya.")
        return 2
    controller = AutopilotController(_home())
    if chosen.manifest.package_type == "REMEDIATION":
        result = controller.run_remediation(repo, chosen.path)
    elif chosen.manifest.package_type == "WORK":
        result = controller.run_package(repo, chosen.path)
    else:
        print(f"Tipe paket {chosen.manifest.package_type} belum dapat dieksekusi dari Smart Inbox.")
        return 2
    print(f"STATUS: {result.status}")
    print(f"TAHAP: {result.stage}")
    print(result.message)
    if result.handoff:
        print(f"HANDOFF GPT: {result.handoff}")
    return 0 if result.status in {"CLEAR", "KNOWN", "WARNING"} else 2



def _recover_project(project_id: str, destination: str | None = None) -> int:
    target = Path(destination).expanduser().resolve() if destination else None
    recovered = ProjectRecoveryManager(_home()).recover(project_id, destination=target)
    print(f"Project berhasil dipulihkan: {recovered}")
    return 0

def _register(repo: str) -> int:
    path = Path(repo).expanduser().resolve()
    profile = load_project_profile(path)
    ProjectRegistry.for_home(_home()).register(profile, path)
    print(f"Project terdaftar: {profile.name}")
    return 0


def _build_handoff(repo_value: str) -> tuple[str, Path]:
    repo = Path(repo_value).expanduser().resolve()
    profile = load_project_profile(repo)
    ProjectRegistry.for_home(_home()).register(profile, repo)
    run = _latest_run(_paths(), profile.project_id)
    if run and run.stage == "WAITING_GPT":
        kind = "INCIDENT"
    elif run:
        kind = "CONTINUITY"
    else:
        kind = "BOOTSTRAP"
    try:
        from .adapters.git import GitAdapter
        git = GitAdapter(repo)
        git_state = git.state(fetch=False)
        technical = {
            "git": {
                "branch": git_state.branch,
                "head": git_state.head,
                "dirty": git_state.dirty,
                "remote": git_state.remote,
                "working_fingerprint": git.working_fingerprint(),
            },
            "profile": profile.to_dict(),
            "run_state": run.to_dict() if run else None,
        }
    except Exception as exc:
        technical = {"profile": profile.to_dict(), "git_error": str(exc), "run_state": run.to_dict() if run else None}
    output = _home() / "storage" / "downloads" / "Expert"
    if not output.parent.exists():
        output = _paths().handoffs
    artifact = HandoffBuilder(output).build(
        kind,
        HandoffContext(
            project_id=profile.project_id,
            project_name=profile.name,
            run_id=run.run_id if run else None,
            milestone=run.milestone if run else None,
            stage=run.stage if run else "IDLE",
            incident_id=run.metadata.get("incident_id") if run else None,
            incident_challenge=run.metadata.get("incident_challenge") if run else None,
            technical=sanitize_mapping(technical),
        ),
    )
    return kind, artifact


def _make_handoff(repo_value: str, fmt: str = "zip") -> int:
    if fmt == "chat":
        return _make_handoff_chat(repo_value)
    kind, artifact = _build_handoff(repo_value)
    clear_screen()
    header()
    print("HANDOFF GPT SIAP")
    print()
    print(f"Jenis          : {kind}")
    print(f"File untuk GPT : {artifact.name}")
    print(f"Lokasi         : {human_path(artifact.parent)}")
    print()
    print('Kirim ke GPT dengan pesan: "Load XP handoff. Lanjutkan dari state terakhir."')
    return 0


def _make_handoff_chat(repo_value: str) -> int:
    repo = Path(repo_value).expanduser().resolve()
    profile = load_project_profile(repo)
    ProjectRegistry.for_home(_home()).register(profile, repo)
    run = _latest_run(_paths(), profile.project_id)
    kind = "INCIDENT" if (run and run.stage == "WAITING_GPT") else ("CONTINUITY" if run else "BOOTSTRAP")
    try:
        git = GitAdapter(repo)
        git_state = git.state(fetch=False)
        technical = {
            "git": {
                "branch": git_state.branch,
                "head": git_state.head,
                "dirty": git_state.dirty,
                "remote": git_state.remote,
                "working_fingerprint": git.working_fingerprint(),
            },
            "profile": profile.to_dict(),
            "run_state": run.to_dict() if run else None,
        }
    except Exception as exc:
        technical = {"profile": profile.to_dict(), "git_error": str(exc), "run_state": run.to_dict() if run else None}
    context = {
        "kind": kind,
        "project_id": profile.project_id,
        "project_name": profile.name,
        "run_id": run.run_id if run else None,
        "milestone": run.milestone if run else None,
        "stage": run.stage if run else "IDLE",
        "incident_id": run.metadata.get("incident_id") if run else None,
        "incident_challenge": run.metadata.get("incident_challenge") if run else None,
        "technical": sanitize_mapping(technical),
    }
    clear_screen()
    header()
    print("HANDOFF CHAT — salin seluruh blok antara BEGIN/END ke AI (Qwen/GPT):")
    print()
    print("===XP_HANDOFF_BEGIN===")
    print(json.dumps(context, indent=2, sort_keys=True, ensure_ascii=False))
    print("===XP_HANDOFF_END===")
    return 0


def _pkg_build(repo_value: str, spec_path: str, out: str | None) -> int:
    from .pkgbuild import build_package_from_spec
    repo = Path(repo_value).expanduser().resolve()
    try:
        artifact = build_package_from_spec(
            _home(), repo, Path(spec_path).expanduser().resolve(),
            Path(out).expanduser().resolve() if out else None,
        )
    except Exception as exc:
        print(f"Paket belum berhasil dibuat: {exc}")
        return 2
    print(f"Paket XP dibuat: {human_path(artifact)}")
    print("Eksekusi via menu Home [2] 'Scan hasil GPT terbaru' atau:")
    print(f"  xp run --repo {repo} {artifact}")
    return 0


def _make_handoff_LEGACY(repo_value: str) -> int:
    kind, artifact = _build_handoff(repo_value)
    clear_screen()
    header()
    print("HANDOFF GPT SIAP")
    print()
    print(f"Jenis          : {kind}")
    print(f"File untuk GPT : {artifact.name}")
    print(f"Lokasi         : {human_path(artifact.parent)}")
    print()
    print('Kirim ke GPT dengan pesan: "Load XP handoff. Lanjutkan dari state terakhir."')
    return 0


def _onboard(repo: str, package: str) -> int:
    repo_path = Path(repo).expanduser().resolve()
    profile = ProjectOnboarder(_home()).apply(repo_path, Path(package))
    print(f"Project siap dikelola XP: {profile.name}")
    print("Membuat Bootstrap GPT handoff agar pekerjaan berikutnya memakai fingerprint source aktual...")
    return _make_handoff(str(repo_path))


def _control_export(output: str) -> int:
    snapshot = ControlStateManager(_home()).export(Path(output))
    print(f"XP recovery state dibuat: {snapshot}")
    return 0


def _control_restore(snapshot: str) -> int:
    ControlStateManager(_home()).restore(Path(snapshot))
    print("Workstation XP berhasil dipulihkan dari control-state.")
    return 0



def _lease_release(project_id: str, run_id: str) -> int:
    cfg = XPConfig.for_home(_home())
    if not cfg.control_repo or not (Path(cfg.control_repo) / ".git").exists():
        print("Control repository belum dikonfigurasi.")
        return 2
    from .control import RemoteLeaseManager, RemoteLeaseError
    try:
        RemoteLeaseManager(Path(cfg.control_repo), device_id=cfg.device_id).release(project_id, run_id, push=True)
    except Exception as exc:
        print(f"Release gagal: {exc}")
        return 2
    print(f"Lease dirilis: {project_id} / {run_id}")
    return 0

def _lease_takeover(project_id: str, run_id: str, yes: bool) -> int:
    cfg = XPConfig.for_home(_home())
    if not cfg.control_repo or not (Path(cfg.control_repo) / ".git").exists():
        print("Control repository belum dikonfigurasi; lease takeover tidak tersedia.")
        return 2
    if not yes:
        print("TAKEOVER WRITER LEASE")
        print()
        print(f"Project : {project_id}")
        print(f"Run     : {run_id}")
        print("Perangkat/run lama kehilangan hak tulis remote sampai lease baru dirilis.")
        print("Gunakan hanya jika perangkat penulis sebelumnya hilang atau tidak aktif.")
        print()
        print("[1] Ya, ambil alih lease")
        print("[0] Batal")
        try:
            choice = input("Pilih: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice != "1":
            return 0
    from .control import RemoteLeaseManager
    try:
        path = RemoteLeaseManager(Path(cfg.control_repo), device_id=cfg.device_id).takeover(project_id, run_id, push=True)
    except Exception as exc:
        print(f"Takeover belum berhasil: {exc}")
        return 2
    print(f"Lease diambil alih: {path.name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xp", add_help=True)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status")
    sub.add_parser("self-test")
    sub.add_parser("version")
    sub.add_parser("audit")
    register = sub.add_parser("register")
    register.add_argument("repo")
    onboard = sub.add_parser("onboard")
    onboard.add_argument("--repo", required=True)
    onboard.add_argument("package")
    handoff = sub.add_parser("handoff")
    handoff.add_argument("--repo", required=True)
    handoff.add_argument("--format", choices=["zip", "chat"], default="zip")
    control_export = sub.add_parser("control-export")
    control_export.add_argument("--output", required=True)
    control_restore = sub.add_parser("control-restore")
    control_restore.add_argument("snapshot")
    recover_project = sub.add_parser("recover-project")
    recover_project.add_argument("project_id")
    recover_project.add_argument("--destination")
    run = sub.add_parser("run")
    run.add_argument("--repo", required=True)
    run.add_argument("package")
    remediate = sub.add_parser("remediate")
    remediate.add_argument("--repo", required=True)
    remediate.add_argument("package")
    db = sub.add_parser("continue-db")
    db.add_argument("--repo", required=True)
    db.add_argument("--run", required=True)
    db.add_argument("--approve", action="store_true")
    qa = sub.add_parser("qa")
    qa.add_argument("--repo", required=True)
    qa.add_argument("--run", required=True)
    group = qa.add_mutually_exclusive_group(required=True)
    group.add_argument("--clear", action="store_true")
    group.add_argument("--problem", action="store_true")
    qa.add_argument("--notes", default="")
    lock = sub.add_parser("lock")
    lock.add_argument("--repo", required=True)
    lock.add_argument("--run", required=True)
    lock.add_argument("--approve", action="store_true")
    takeover = sub.add_parser("lease-takeover")
    takeover.add_argument("--project", required=True)
    takeover.add_argument("--run", required=True)
    takeover.add_argument("--yes", action="store_true")
    pkgbuild = sub.add_parser("pkg-build")
    proj = sub.add_parser("project", help="Project management")
    proj_sub = proj.add_subparsers(dest="action")
    proj_init = proj_sub.add_parser("init", help="Buat project baru dari template")
    proj_init.add_argument("name", help="Nama project")
    proj_add = proj_sub.add_parser("add", help="Daftarkan repo existing")
    proj_add.add_argument("path", help="Path ke repo")
    proj_sub.add_parser("list", help="List semua project terdaftar")
    proj_switch = proj_sub.add_parser("switch", help="Ganti project aktif")
    proj_switch.add_argument("project_id", help="Project ID")
    sub.add_parser("upgrade", help="Upgrade XP")
    sub.add_parser("check", help="Cek dependency")
    sub.add_parser("sweep", help="Sweep folder Download untuk file XP")
    sub.add_parser("handshake", help="Print panduan sambung untuk AI external")
    parser_help = sub.add_parser("help", help="Tampilkan bantuan")
    parser_help.add_argument("topic", nargs="?", help="Topik bantuan")


    bundle = sub.add_parser("bundle")
    bundle.add_argument("--repo", required=True)
    pkgbuild.add_argument("--repo", required=True)
    pkgbuild.add_argument("--spec", required=True)
    pkgbuild.add_argument("--out")
    leaserelease = sub.add_parser("lease-release")
    leaserelease.add_argument("--project", required=True)
    leaserelease.add_argument("--run", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command is None:
        return _home_screen()
    if args.command == "status":
        return _status()
    if args.command == "self-test":
        return _self_test()
    if args.command == "version":
        print(f"Expert Workstation XP {__version__}")
        return 0
    if args.command == "audit":
        return _audit()
    if args.command == "register":
        return _register(args.repo)
    if args.command == "onboard":
        return _onboard(args.repo, args.package)
    if args.command == "handoff":
        return _make_handoff(args.repo, fmt=getattr(args, "format", "zip"))
    if args.command == "control-export":
        return _control_export(args.output)
    if args.command == "control-restore":
        return _control_restore(args.snapshot)
    if args.command == "recover-project":
        return _recover_project(args.project_id, args.destination)
    if args.command == "run":
        result = AutopilotController(_home()).run_package(Path(args.repo), Path(args.package))
        print(f"STATUS: {result.status}")
        print(f"TAHAP: {result.stage}")
        print(result.message)
        if result.handoff:
            print(f"HANDOFF GPT: {result.handoff}")
        return 0 if result.status in {"CLEAR", "KNOWN", "WARNING"} else 2
    if args.command == "remediate":
        result = AutopilotController(_home()).run_remediation(Path(args.repo), Path(args.package))
        print(f"STATUS: {result.status}")
        print(f"TAHAP: {result.stage}")
        print(result.message)
        if result.handoff:
            print(f"HANDOFF GPT: {result.handoff}")
        return 0 if result.status in {"CLEAR", "KNOWN", "WARNING"} else 2
    if args.command == "continue-db":
        result = AutopilotController(_home()).continue_database(Path(args.repo), args.run, approved=args.approve)
        print(f"STATUS: {result.status}")
        print(f"TAHAP: {result.stage}")
        print(result.message)
        if result.handoff:
            print(f"HANDOFF GPT: {result.handoff}")
        return 0 if result.status in {"CLEAR", "KNOWN", "WARNING"} else 2
    if args.command == "qa":
        result = AutopilotController(_home()).record_human_qa(Path(args.repo), args.run, clear=args.clear, notes=args.notes)
        print(f"STATUS: {result.status}")
        print(f"TAHAP: {result.stage}")
        print(result.message)
        if result.handoff:
            print(f"HANDOFF GPT: {result.handoff}")
        return 0 if result.status in {"CLEAR", "KNOWN", "WARNING"} else 2
    if args.command == "lock":
        result = AutopilotController(_home()).final_lock(Path(args.repo), args.run, approved=args.approve)
        print(f"STATUS: {result.status}")
        print(f"TAHAP: {result.stage}")
        print(result.message)
        if result.handoff:
            print(f"HANDOFF GPT: {result.handoff}")
        return 0 if result.status in {"CLEAR", "KNOWN", "WARNING"} else 2
    if args.command == "bundle":
        return _bundle_cmd(args.repo)
    if args.command == "project":
        if args.action == "init":
            return _project_init(args.name)
        elif args.action == "add":
            return _project_add(args.path)
        elif args.action == "list":
            return _project_list()
        elif args.action == "switch":
            return _project_switch(args.project_id)
        else:
            print("ERROR: action tidak dikenali")
            return 1
    if args.command == "help":
        return _help_cmd(args.topic)
    if args.command == "handshake":
        return _handshake_cmd()
    if args.command == "sweep":
        return _sweep_cmd()
    if args.command == "upgrade":
        return _upgrade_cmd()
    if args.command == "check":
        return _check_cmd()
    if args.command == "pkg-build":
        return _pkg_build(args.repo, args.spec, args.out)
    if args.command == "lease-release":
        return _lease_release(args.project, args.run)
    if args.command == "lease-takeover":
        return _lease_takeover(args.project, args.run, args.yes)
    return 2




def _bundle_cmd(repo_arg: str) -> int:
    import time
    import dataclasses
    from . import __version__
    repo = Path(repo_arg).expanduser().resolve()
    if not (repo / ".xp" / "project.json").exists():
        print(f"ERROR: {repo} bukan project XP (tidak ada .xp/project.json)")
        return 1
    profile = load_project_profile(repo)
    paths = _paths()
    cfg = XPConfig.for_home(paths.home)
    lines: list[str] = []
    lines.append("# XP CONTEXT BUNDLE — BACA DULU SEBELUM MENJAWAB")
    lines.append(f"XP version: {__version__}")
    lines.append(f"Generated: {time.strftime('%Y-%m-%dT%H:%M:%S')}")
    lines.append(f"Device ID: {cfg.device_id}")
    lines.append("")
    lines.append("INSTRUKSI UNTUK AI PENERIMA:")
    lines.append("Anda adalah kelanjutan arsitek project ini. Baca seluruh bundle berurutan:")
    lines.append("aturan workflow (blueprint), state project, lalu source engine XP di bagian akhir.")
    lines.append("Jangan pernah menyentuh filesystem atau menjalankan perintah mutasi langsung.")
    lines.append("Kirim hanya spec.json deklaratif; user akan menjalankannya lewat: xp pkg-build lalu menu XP.")
    lines.append("")
    lines.append("===== PROJECT REGISTRY =====")
    registry = ProjectRegistry.for_home(paths.home)
    for item in registry.list_projects():
        lines.append(f"- {item.project_id} | {item.name} | repo: {item.repo_path or '(remote-only)'}")
    lines.append("")
    lines.append("===== PROFILE (.xp/project.json) =====")
    lines.append((repo / ".xp" / "project.json").read_text(encoding="utf-8"))
    lines.append("===== POLICIES (.xp/policies.json) =====")
    lines.append((repo / ".xp" / "policies.json").read_text(encoding="utf-8"))
    lines.append("===== COMPATIBILITY (.xp/compatibility.json) =====")
    lines.append((repo / ".xp" / "compatibility.json").read_text(encoding="utf-8"))
    bp = repo / "docs" / "blueprint" / "15_WORKFLOW_PROFILE.md"
    if bp.is_file():
        lines.append("===== BLUEPRINT SNAPSHOT (15_WORKFLOW_PROFILE.md) =====")
        lines.append(bp.read_text(encoding="utf-8"))
    rm = repo / "docs" / "checkpoints" / "ROADMAP_PROGRESS.md"
    if rm.is_file():
        lines.append("===== ROADMAP SNAPSHOT (ROADMAP_PROGRESS.md) =====")
        lines.append(rm.read_text(encoding="utf-8"))
    lines.append("===== CHECKPOINTS TERKUNCI (via XP) =====")
    for milestone in _list_locked_milestones(profile.project_id):
        lines.append(f"- {milestone}")
    latest = _latest_run(paths, profile.project_id)
    if latest is not None:
        lines.append("===== RUN STATE TERAKHIR =====")
        lines.append(json.dumps(dataclasses.asdict(latest), indent=2, default=str))
    lines.append("===== SOURCE ENGINE XP =====")
    src_root = Path(__file__).resolve().parent
    for py in sorted(src_root.rglob("*.py")):
        lines.append(f"##### FILE: {py.name} #####")
        lines.append(py.read_text(encoding="utf-8"))
    out_dir = paths.home / "storage" / "downloads" / "Expert"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = out_dir / f"XP_BUNDLE_{profile.project_id}_{stamp}.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Bundle dibuat: {out}")
    print(f"Ukuran: {out.stat().st_size} bytes. Lampirkan file ini ke chat AI baru (jangan paste manual).")
    return 0



def _project_init(name: str) -> int:
    from datetime import date
    import shutil
    try:
        from .models import ProjectProfile
    except ImportError:
        from .project_registry import ProjectProfile
    
    projects_dir = Path.home() / "WORKSTATION" / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    
    project_path = projects_dir / name
    if project_path.exists():
        print(f"ERROR: Folder {project_path} sudah ada")
        return 1
    
    print(f"=== Membuat project: {name} ===")
    project_path.mkdir(parents=True)
    
    # Git init
    import subprocess
    subprocess.run(["git", "init"], cwd=project_path, check=True, capture_output=True)
    print("✓ git init")
    
    # Copy templates
    templates = Path(__file__).parent / "templates" / "project"
    xp_dir = project_path / ".xp"
    xp_dir.mkdir()
    
    project_id = name.replace(" ", "-").lower()
    project_name = name.replace("-", " ").title()
    today = date.today().isoformat()
    
    # project.json
    pj = json.loads((templates / "project.json").read_text(encoding="utf-8"))
    pj["project_id"] = project_id
    pj["name"] = project_name
    (xp_dir / "project.json").write_text(json.dumps(pj, indent=2), encoding="utf-8")
    print("✓ .xp/project.json")
    
    # policies.json
    shutil.copy(templates / "policies.json", xp_dir / "policies.json")
    print("✓ .xp/policies.json")
    
    # compatibility.json
    shutil.copy(templates / "compatibility.json", xp_dir / "compatibility.json")
    print("✓ .xp/compatibility.json")
    
    # scripts/verify.mjs
    scripts_dir = project_path / "scripts"
    scripts_dir.mkdir()
    shutil.copy(templates / "verify.mjs", scripts_dir / "verify.mjs")
    print("✓ scripts/verify.mjs")
    
    # docs/blueprint/README.md
    bp_dir = project_path / "docs" / "blueprint"
    bp_dir.mkdir(parents=True)
    bp_text = (templates / "blueprint.md").read_text(encoding="utf-8")
    bp_text = bp_text.replace("{{PROJECT_NAME}}", project_name).replace("{{DATE}}", today)
    (bp_dir / "README.md").write_text(bp_text, encoding="utf-8")
    print("✓ docs/blueprint/README.md")
    
    # docs/checkpoints/ROADMAP_PROGRESS.md
    cp_dir = project_path / "docs" / "checkpoints"
    cp_dir.mkdir(parents=True)
    rm_text = (templates / "roadmap.md").read_text(encoding="utf-8")
    rm_text = rm_text.replace("{{PROJECT_NAME}}", project_name)
    (cp_dir / "ROADMAP_PROGRESS.md").write_text(rm_text, encoding="utf-8")
    print("✓ docs/checkpoints/ROADMAP_PROGRESS.md")
    
    # README.md
    readme_text = (templates / "readme.md").read_text(encoding="utf-8")
    readme_text = readme_text.replace("{{PROJECT_NAME}}", project_name)
    (project_path / "README.md").write_text(readme_text, encoding="utf-8")
    print("✓ README.md")
    
    # .gitignore
    shutil.copy(templates / "gitignore", project_path / ".gitignore")
    print("✓ .gitignore")
    
    # Initial commit
    subprocess.run(["git", "add", "."], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "feat: initial project scaffold"], 
                   cwd=project_path, check=True, capture_output=True)
    print("✓ git commit")
    
    # Register project
    registry = ProjectRegistry.for_home(_paths().home)
    registry.register(load_project_profile(project_path), project_path)
    print(f"✓ Project terdaftar di registry")
    
    print(f"\n=== Project {name} berhasil dibuat ===")
    print(f"Path: {project_path}")
    print(f"\nLangkah selanjutnya:")
    print(f"  1. cd {project_path}")
    print(f"  2. xp")
    print(f"  3. Pilih [3] Pilih project lain → {project_name}")
    print(f"  4. Mulai pekerjaan pertama Anda")
    return 0


def _project_add(path_str: str) -> int:
    try:
        from .models import ProjectProfile
    except ImportError:
        from .project_registry import ProjectProfile
    project_path = Path(path_str).expanduser().resolve()
    if not project_path.exists():
        print(f"ERROR: Path {project_path} tidak ada")
        return 1
    
    xp_dir = project_path / ".xp"
    if not xp_dir.exists():
        print(f"ERROR: Folder .xp tidak ditemukan di {project_path}")
        print(f"Apakah ini project XP? Jika belum, jalankan: xp project init <name>")
        return 1
    
    profile = load_project_profile(project_path)
    registry = ProjectRegistry.for_home(_paths().home)
    registry.register(profile, project_path)
    print(f"✓ Project {profile.name} terdaftar di registry")
    print(f"Path: {project_path}")
    return 0


def _project_list() -> int:
    registry = ProjectRegistry.for_home(_paths().home)
    projects = registry.list_projects()
    if not projects:
        print("Belum ada project terdaftar.")
        print("\nBuat project baru: xp project init <name>")
        return 0
    
    print(f"Project terdaftar ({len(projects)}):")
    for p in projects:
        print(f"  - {p.project_id} | {p.name} | {p.repo_path or '(remote-only)'}")
    return 0


def _project_switch(project_id: str) -> int:
    registry = ProjectRegistry.for_home(_paths().home)
    projects = registry.list_projects()
    target = None
    for p in projects:
        if p.project_id == project_id:
            target = p
            break
    
    if not target:
        print(f"ERROR: Project {project_id} tidak ditemukan")
        print(f"\nProject terdaftar:")
        for p in projects:
            print(f"  - {p.project_id}")
        return 1
    
    registry.activate(target.project_id)
    print(f"✓ Project aktif: {target.name} ({target.project_id})")
    return 0





def _help_cmd(topic: str | None = None) -> int:
    """Tampilkan bantuan untuk command atau topik"""
    docs_dir = Path.home() / ".expert-workstation" / "engine" / "docs"
    
    if topic is None:
        print("\n=== Dokumentasi Expert Workstation ===\n")
        topics = [
            ("quickstart", "Cara mulai menggunakan XP"),
            ("workflow", "Siklus kerja: spec → build → apply → lock"),
            ("commands", "Daftar semua command yang tersedia"),
            ("concepts", "Konsep inti: checkpoint, milestone, dll"),
            ("project-setup", "Cara setup project baru"),
            ("troubleshooting", "Solusi masalah umum"),
            ("architecture", "Arsitektur internal XP"),
        ]
        for name, desc in topics:
            print(f"  {name:20} - {desc}")
        print("\nGunakan: xp help <topik>")
        print("Contoh: xp help workflow\n")
        return 0
    
    topic_file = docs_dir / f"{topic}.md"
    if not topic_file.exists():
        print(f"ERROR: Topik '{topic}' tidak ditemukan")
        print(f"Topik yang tersedia: quickstart, workflow, commands, concepts, project-setup, troubleshooting, architecture")
        return 1
    
    content = topic_file.read_text(encoding="utf-8")
    print(content)
    return 0




def _sweep_cmd() -> int:
    """Sweep folder Download untuk file XP_*.zip dan pindahkan ke folder pantauan"""
    import shutil
    
    # Folder kandidat Download
    download_dirs = [
        Path.home() / "Downloads",
        Path.home() / "storage" / "shared" / "Download",
        Path("/storage/emulated/0/Download"),
    ]
    
    # Folder tujuan (folder pantauan XP)
    expert_dir = Path.home() / "storage" / "downloads" / "Expert"
    expert_dir.mkdir(parents=True, exist_ok=True)
    
    print("=== Sweep Download Folders ===")
    print(f"Target: {expert_dir}\n")
    
    moved = []
    skipped = []
    
    for d in download_dirs:
        if not d.exists():
            continue
        
        print(f"Scanning: {d}")
        for zip_file in d.glob("XP_*.zip"):
            dest = expert_dir / zip_file.name
            
            # Cek duplikat
            if dest.exists():
                skipped.append((zip_file, "already exists"))
                print(f"  SKIP {zip_file.name} (sudah ada di tujuan)")
                continue
            
            # Pindahkan
            try:
                shutil.move(str(zip_file), str(dest))
                moved.append((zip_file, dest))
                print(f"  MOVED {zip_file.name}")
            except Exception as e:
                print(f"  ERROR {zip_file.name}: {e}")
        print()
    
    print("=== Summary ===")
    print(f"Moved: {len(moved)} files")
    print(f"Skipped: {len(skipped)} files")
    
    if moved:
        print(f"\nJalankan 'xp' lalu pilih [2] untuk scan paket yang baru dipindahkan")
    
    return 0




def _handshake_cmd() -> int:
    """Print panduan sambung XP untuk AI external"""
    doc = Path.home() / ".expert-workstation" / "engine" / "docs" / "handshake.md"
    if not doc.exists():
        print("ERROR: docs/handshake.md tidak ditemukan di engine")
        return 1
    print(doc.read_text(encoding="utf-8"))
    return 0


def _upgrade_cmd() -> int:
    import subprocess, shutil, re
    paths = _paths()
    engine_path = Path.home() / ".expert-workstation" / "engine"
    if not engine_path.exists():
        print("ERROR: engine tidak ditemukan")
        return 1
    print("=== Upgrade XP ===")
    subprocess.run(["git", "fetch", "origin", "xp-engine"], cwd=engine_path)
    subprocess.run(["git", "checkout", "xp-engine"], cwd=engine_path)
    subprocess.run(["git", "pull", "origin", "xp-engine"], cwd=engine_path)
    init_text = (engine_path / "src" / "xp" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', init_text)
    if not match:
        print("ERROR: parse version gagal")
        return 1
    new_version = match.group(1)
    print(f"Versi baru: {new_version}")
    new_dir = paths.home / "versions" / new_version
    if new_dir.exists():
        shutil.rmtree(new_dir)
    new_dir.mkdir(parents=True)
    (new_dir / "src").mkdir()
    shutil.copytree(engine_path / "src" / "xp", new_dir / "src" / "xp")
    (paths.home / "active-version").write_text(new_version, encoding="utf-8")
    print(f"Upgrade ke {new_version} selesai")
    return 0


def _check_cmd() -> int:
    import subprocess, shutil
    print("=== Dependency Check ===")
    for name, cmd in [("python", "python3"), ("node", "node"), ("git", "git"), ("psql", "psql"), ("gh", "gh")]:
        if shutil.which(cmd):
            result = subprocess.run([cmd, "--version"], capture_output=True, text=True)
            version = (result.stdout.strip() or result.stderr.strip()).split("\n")[0]
            print(f"OK {name}: {version}")
        else:
            print(f"MISSING {name}: tidak ditemukan")
    if shutil.which("gh"):
        print("=== GitHub CLI ===")
        result = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
        print("OK gh auth: logged in" if result.returncode == 0 else "MISSING gh auth: belum login")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
