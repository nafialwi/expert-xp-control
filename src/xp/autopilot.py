from __future__ import annotations

import json
import os
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters.base import AdapterError
from .adapters.git import GitAdapter
from .adapters.node import NodeAdapter
from .adapters.postgresql import PostgreSQLAdapter, classify_sql
from .adapters.python_runtime import PythonAdapter
from .executor import PackageExecutor
from .config import XPConfig
from .control import ControlStateError, ControlStateManager, RemoteLeaseError, RemoteLeaseManager
from .handoff import HandoffBuilder, HandoffContext
from .journal import Journal
from .locks import ProjectLock, ProjectLockedError
from .models import RunState
from .packages import RunContext, inspect_package, stage_package, validate_package
from .paths import XPPaths
from .project_registry import ProjectRegistry, load_project_profile
from .state_store import StateStore
from .storage import StorageManager
from .warnings import classify_warnings
from .ui import Spinner


@dataclass(frozen=True)
class AutopilotResult:
    status: str
    stage: str
    message: str
    run_id: str | None = None
    handoff: Path | None = None


class AutopilotController:
    def __init__(self, user_home: Path):
        self.user_home = Path(user_home).expanduser().resolve()
        self.paths = XPPaths.from_home(self.user_home)
        self.paths.ensure_runtime_dirs()
        self.state_store = StateStore(self.paths)
        self.config = XPConfig.for_home(self.user_home)

    def _control_repo(self) -> Path | None:
        if not self.config.control_repo:
            return None
        path = Path(self.config.control_repo).expanduser().resolve()
        return path if (path / ".git").exists() else None

    def _sync_control_state(self, state: RunState) -> bool:
        control_repo = self._control_repo()
        if control_repo is None:
            state.metadata["control_sync"] = "NOT_CONFIGURED"
            self.state_store.save(state)
            return True
        try:
            ControlStateManager(self.user_home).sync_to_repo(control_repo, push=True)
        except Exception as exc:
            state.metadata["control_sync"] = "PENDING"
            state.metadata["control_sync_error"] = str(exc)
            self.state_store.save(state)
            return False
        state.metadata["control_sync"] = "CLEAR"
        state.metadata.pop("control_sync_error", None)
        self.state_store.save(state)
        return True

    def _acquire_remote_lease(self, profile, state: RunState) -> AutopilotResult | None:
        control_repo = self._control_repo()
        if control_repo is None:
            return None
        try:
            RemoteLeaseManager(control_repo, device_id=self.config.device_id).acquire(
                profile.project_id, state.run_id, push=True
            )
        except RemoteLeaseError as exc:
            return self._failure_handoff(
                Path(str(state.metadata.get("repo", "."))), profile, state,
                "Project sedang memiliki active writer di perangkat/run lain; recovery/takeover diperlukan.",
                {"remote_lease_error": str(exc)},
            )
        except Exception as exc:
            state.stage = "REMOTE_UNAVAILABLE"
            state.metadata["resume_target"] = "REMOTE_LEASE"
            state.metadata["remote_lease_error"] = str(exc)
            self._save(state)
            return AutopilotResult(
                "WARNING", state.stage,
                "Remote writer protection belum dapat diverifikasi; source belum diubah.",
                state.run_id,
            )
        state.metadata["remote_lease"] = "ACTIVE"
        self._save(state)
        self._sync_control_state(state)
        return None

    def _release_remote_lease(self, profile, state: RunState) -> bool:
        control_repo = self._control_repo()
        if control_repo is None or state.metadata.get("remote_lease") != "ACTIVE":
            return True
        try:
            RemoteLeaseManager(control_repo, device_id=self.config.device_id).release(
                profile.project_id, state.run_id, push=True
            )
        except Exception as exc:
            state.metadata["remote_lease_release"] = "PENDING"
            state.metadata["remote_lease_release_error"] = str(exc)
            self._save(state)
            return False
        state.metadata["remote_lease"] = "RELEASED"
        state.metadata["remote_lease_release"] = "CLEAR"
        state.metadata.pop("remote_lease_release_error", None)
        self._save(state)
        return True

    def _load_policy(self, repo: Path) -> dict[str, Any]:
        path = repo / ".xp" / "policies.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, state: RunState) -> None:
        previous = str(state.metadata.get("_last_stage") or "")
        if previous and previous != state.stage:
            from .workflow import transition_allowed
            if not transition_allowed(previous, state.stage):
                log = list(state.metadata.get("transition_warnings") or [])
                log.append(f"{previous}->{state.stage}")
                state.metadata["transition_warnings"] = log
        state.metadata["_last_stage"] = state.stage
        self.state_store.save(state)

    def _failure_handoff(
        self,
        repo: Path,
        profile,
        state: RunState,
        message: str,
        technical: dict[str, Any] | None = None,
        *,
        outcome: str = "ERROR",
    ) -> AutopilotResult:
        incident_id = str(state.metadata.get("incident_id") or f"INC-{secrets.token_hex(4).upper()}")
        challenge = str(state.metadata.get("incident_challenge") or secrets.token_hex(16))
        state.stage = "WAITING_GPT"
        state.metadata.update(
            {
                "incident_id": incident_id,
                "incident_challenge": challenge,
                "failure_message": message,
                "repo": str(repo),
            }
        )
        self._save(state)
        technical_payload = dict(technical or {})
        technical_payload.setdefault("message", message)
        technical_payload.setdefault("stage", state.stage)
        handoff = HandoffBuilder(self.paths.handoffs).build(
            "INCIDENT",
            HandoffContext(
                project_id=profile.project_id,
                project_name=profile.name,
                run_id=state.run_id,
                milestone=state.milestone,
                stage=state.stage,
                incident_id=incident_id,
                incident_challenge=challenge,
                technical=technical_payload,
            ),
        )
        downloads = self.user_home / "storage" / "downloads"
        if downloads.exists():
            expert_dir = downloads / "Expert"
            expert_dir.mkdir(parents=True, exist_ok=True)
            published = expert_dir / handoff.name
            shutil.copy2(handoff, published)
            handoff = published
        self._sync_control_state(state)
        return AutopilotResult(outcome, "WAITING_GPT", message, state.run_id, handoff)

    def _verify_source(self, repo: Path, policy: dict[str, Any]) -> tuple[bool, str, str, tuple[str, ...]]:
        steps = list(policy.get("source_verify") or [])
        if not steps:
            return True, "No source verification steps declared", "CLEAR", ()
        logs: list[str] = []
        for step in steps:
            adapter = step.get("adapter")
            try:
                if adapter == "python":
                    module = str(step.get("module", "unittest"))
                    runner = PythonAdapter(repo, allowed_modules={module})
                    result = runner.run_module(module, [str(x) for x in step.get("args", [])])
                elif adapter == "node":
                    runner = NodeAdapter(repo)
                    result = runner.run_script(str(step["script"]))
                else:
                    return False, f"Unsupported verify adapter: {adapter}", "ERROR", ()
            except Exception as exc:
                from .redaction import redact_text
                return False, f"Source verification tidak selesai: {redact_text(str(exc))}", "ERROR", ()
            logs.extend([result.stdout, result.stderr])
            if result.returncode != 0:
                return False, "\n".join(logs), "ERROR", ()
        log_text = "\n".join(logs)
        warning_policy = dict(policy.get("warnings") or {})
        warning_result = classify_warnings(
            log_text,
            known_markers=list(warning_policy.get("known") or []),
            detect_markers=list(warning_policy.get("detect") or []),
        )
        return True, log_text, warning_result.status, warning_result.unknown

    def _store_package(self, package_path: Path, run_id: str) -> Path:
        run_dir = self.paths.runs / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        stored = run_dir / "package.zip"
        shutil.copy2(package_path, stored)
        return stored

    def _psql(self) -> PostgreSQLAdapter:
        return PostgreSQLAdapter(psql_bin=os.environ.get("XP_PSQL_BIN", "psql"))

    def _run_db_tests(self, repo: Path, state: RunState, operations: list[dict[str, Any]], profile) -> AutopilotResult | None:
        tests = [op for op in operations if op.get("type") == "RUN_SQL_TEST"]
        if not tests:
            return None
        adapter = self._psql()
        env = adapter.environment_status(check_connection=True)
        if not env.connection_ok:
            state.stage = "REMOTE_UNAVAILABLE"
            state.metadata["resume_target"] = "DB_VERIFICATION"
            state.metadata["db_environment_message"] = env.message
            self._save(state)
            return AutopilotResult("WARNING", state.stage, "Database belum dapat dijangkau; source tetap aman.", state.run_id)
        journal = Journal(self.paths.runs / state.run_id / "journal.jsonl")
        for op in tests:
            sql_path = (repo / str(op["path"])).resolve()
            if repo not in sql_path.parents:
                return self._failure_handoff(repo, profile, state, "SQL test path keluar dari repository.")
            entry = journal.before("DB_TEST", {"path": str(op["path"])})
            result = adapter.run_test_file(sql_path)
            journal.after(entry, "CLEAR" if result.applied else "ERROR", {"returncode": result.returncode})
            if not result.applied:
                return self._failure_handoff(
                    repo,
                    profile,
                    state,
                    "Database regression gagal.",
                    {"path": str(op["path"]), "stdout": result.stdout, "stderr": result.stderr},
                )
        state.metadata["db_verified"] = True
        self._save(state)
        return None

    def _remote_safepoint(self, repo: Path, state: RunState, policy: dict[str, Any], profile) -> AutopilotResult | None:
        remote_policy = dict(policy.get("remote_safepoint") or {})
        if not remote_policy.get("enabled", False):
            state.stage = "REMOTE_SAFEPOINT"
            state.metadata["remote_safepoint"] = "DISABLED"
            self._save(state)
            return None
        state.stage = "REMOTE_SAFEPOINT_PENDING"
        self._save(state)
        try:
            result = GitAdapter(repo).create_safepoint(
                f"xp(safepoint): {state.milestone or state.run_id} source verified",
                push=True,
                remote=str(remote_policy.get("remote", "origin")),
            )
        except AdapterError as exc:
            state.stage = "REMOTE_UNAVAILABLE"
            state.metadata["resume_target"] = "REMOTE_SAFEPOINT"
            state.metadata["remote_error"] = str(exc)
            self._save(state)
            return AutopilotResult("WARNING", state.stage, "Source clear secara lokal, tetapi belum terlindungi di remote.", state.run_id)
        state.stage = "REMOTE_SAFEPOINT"
        state.metadata.update({"remote_safepoint": "CLEAR", "safepoint_head": result.head, "safepoint_pushed": result.pushed})
        self._save(state)
        return None

    def run_package(self, repo: Path, package_path: Path) -> AutopilotResult:
        repo = Path(repo).expanduser().resolve()
        package_path = Path(package_path).expanduser().resolve()
        profile = load_project_profile(repo)
        policy = self._load_policy(repo)
        ProjectRegistry.for_home(self.user_home).register(profile, repo)
        git = GitAdapter(repo)
        try:
            git_state = git.state(fetch=True)
        except Exception as exc:
            dummy = RunState(profile.project_id, f"{profile.project_id}-unstarted", "FAILED_SAFE")
            return self._failure_handoff(repo, profile, dummy, f"Git state unavailable: {exc}")

        if git_state.remote and git_state.fetch_checked and git_state.fetch_ok is False:
            return AutopilotResult(
                "WARNING",
                "REMOTE_UNAVAILABLE",
                "Remote Git belum dapat diverifikasi; source belum diubah. Periksa jaringan/auth lalu ulangi.",
                None,
            )

        protected = set(policy.get("protected_branches") or ["main", "master"])
        allowed_prefixes = tuple(policy.get("allowed_branch_prefixes") or ["work/", "xp/recovery/"])
        if git_state.branch in protected or (allowed_prefixes and not any((git_state.branch or "").startswith(p) for p in allowed_prefixes)):
            run = RunState(profile.project_id, f"{profile.project_id}-blocked", "FAILED_SAFE")
            return self._failure_handoff(
                repo, profile, run, "Branch tidak memenuhi policy XP; source tidak diubah.",
                {"branch": git_state.branch, "protected": sorted(protected), "allowed_prefixes": allowed_prefixes},
            )
        if git_state.dirty:
            run = RunState(profile.project_id, f"{profile.project_id}-blocked", "FAILED_SAFE")
            return self._failure_handoff(repo, profile, run, "Project memiliki perubahan lokal sebelum pekerjaan dimulai; source tidak diubah.")
        if git_state.diverged or git_state.behind:
            run = RunState(profile.project_id, f"{profile.project_id}-blocked", "FAILED_SAFE")
            return self._failure_handoff(
                repo, profile, run,
                "Branch kerja tertinggal atau diverged dari remote; source tidak diubah sebelum sinkronisasi diaudit.",
                {"ahead": git_state.ahead, "behind": git_state.behind, "diverged": git_state.diverged},
            )

        manifest = inspect_package(package_path)
        base_fp = git.working_fingerprint()
        context = RunContext(project_id=profile.project_id, stage="IDLE", base_fingerprint=base_fp)
        report = validate_package(manifest, context)
        run_id = manifest.run_id or f"{profile.project_id}-{manifest.milestone or 'work'}-{secrets.token_hex(4)}"
        state = RunState(profile.project_id, run_id, "PREPARING", manifest.milestone)
        required_space = max(64 * 1024 * 1024, package_path.stat().st_size * 8)
        storage = StorageManager(self.paths.root).preflight(required_space)
        if not storage.ok:
            self._save(state)
            return self._failure_handoff(
                repo, profile, state,
                "Penyimpanan perangkat tidak cukup untuk menjalankan paket dengan aman; source tidak diubah.",
                {"free_bytes": storage.free_bytes, "required_bytes": storage.required_bytes},
            )
        stored_package = self._store_package(package_path, run_id)
        state.metadata.update({
            "package": str(stored_package),
            "base_fingerprint": base_fp,
            "repo": str(repo),
            "branch": git_state.branch,
            "head": git_state.head,
        })
        self._save(state)
        if report.status != "CLEAR":
            return self._failure_handoff(repo, profile, state, "Paket XP tidak cocok dengan kondisi project.", {"reasons": report.reasons})

        lock = ProjectLock(self.paths.locks, profile.project_id, run_id)
        try:
            lock.acquire()
        except ProjectLockedError as exc:
            return self._failure_handoff(repo, profile, state, str(exc))
        journal = Journal(self.paths.runs / run_id / "journal.jsonl")
        staging = self.paths.runs / run_id / "staging"
        backup_root = self.paths.backups / profile.project_id / run_id
        try:
            staged = stage_package(stored_package, staging)
            preflight = PackageExecutor(repo).preflight(staged)
            if preflight.status != "CLEAR":
                return self._failure_handoff(repo, profile, state, "Preflight source package gagal.", {"reasons": preflight.reasons})
            state.stage = "PACKAGE_VALIDATED"
            self._save(state)
            lease_result = self._acquire_remote_lease(profile, state)
            if lease_result:
                return lease_result

            state.stage = "SOURCE_APPLYING"
            self._save(state)
            entry = journal.before("SOURCE_APPLY", {"package": stored_package.name})
            try:
                exec_result = PackageExecutor(repo).apply(staged, backup_root=backup_root)
            except Exception as exc:
                journal.after(entry, "ERROR", {"message": str(exc)})
                return self._failure_handoff(repo, profile, state, f"Source apply gagal: {exc}")
            journal.after(entry, "CLEAR", {"changed_paths": exec_result.changed_paths})
            state.stage = "SOURCE_APPLIED"
            state.metadata["changed_paths"] = list(exec_result.changed_paths)
            self._save(state)

            verify_entry = journal.before("SOURCE_VERIFY", {})
            with Spinner("Verifikasi source (gate kanonik) berjalan — layar TIDAK hang"):
                ok, verify_log, warning_status, unknown_warnings = self._verify_source(repo, policy)
            journal.after(verify_entry, "CLEAR" if ok else "ERROR", {"warning_status": warning_status})
            if not ok:
                diff = git._run("diff", "--binary", "HEAD", "--", check=False)
                return self._failure_handoff(repo, profile, state, "Source verification gagal.", {"verify_log": verify_log, "git_diff": diff})
            if warning_status == "WARNING":
                diff = git._run("diff", "--binary", "HEAD", "--", check=False)
                return self._failure_handoff(
                    repo, profile, state, "Warning baru memerlukan audit GPT.",
                    {"unknown_warnings": unknown_warnings, "verify_log": verify_log, "git_diff": diff}, outcome="WARNING",
                )
            state.stage = "SOURCE_VERIFIED"
            state.metadata["working_fingerprint"] = git.working_fingerprint()
            state.metadata["warning_status"] = warning_status
            self._save(state)

            remote_result = self._remote_safepoint(repo, state, policy, profile)
            if remote_result:
                return remote_result

            db_ops = [op for op in manifest.operations if op.get("type") in {"APPLY_DB_MIGRATION", "RUN_SQL_TEST"}]
            if any(op.get("type") == "APPLY_DB_MIGRATION" for op in db_ops):
                state.stage = "DB_APPROVAL_REQUIRED"
                self._save(state)
                return AutopilotResult("CLEAR", state.stage, "Source clear; perubahan database menunggu approval manusia.", run_id)

            db_result = self._run_db_tests(repo, state, db_ops, profile)
            if db_result:
                return db_result
            state.stage = "HUMAN_QA"
            self._save(state)
            self._sync_control_state(state)
            return AutopilotResult("CLEAR", state.stage, "Automated gates clear; human QA required.", run_id)
        finally:
            lock.release()
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    def continue_database(self, repo: Path, run_id: str, *, approved: bool) -> AutopilotResult:
        repo = Path(repo).expanduser().resolve()
        profile = load_project_profile(repo)
        state = self.state_store.load(run_id)
        if state.project_id != profile.project_id:
            return self._failure_handoff(repo, profile, state, "Run/project identity mismatch.")
        if state.stage != "DB_APPROVAL_REQUIRED":
            return self._failure_handoff(repo, profile, state, f"Database continuation tidak valid dari state {state.stage}.")
        if not approved:
            state.stage = "PAUSED_BY_USER"
            state.metadata["resume_target"] = "DB_APPROVAL_REQUIRED"
            self._save(state)
            return AutopilotResult("KNOWN", state.stage, "Pekerjaan dipause oleh pengguna sebelum perubahan database.", run_id)
        package_path = Path(str(state.metadata["package"]))
        manifest = inspect_package(package_path)
        operations = list(manifest.operations)
        migrations = [op for op in operations if op.get("type") == "APPLY_DB_MIGRATION"]
        tests = [op for op in operations if op.get("type") == "RUN_SQL_TEST"]
        if migrations and not tests:
            return self._failure_handoff(repo, profile, state, "Migration tidak memiliki SQL regression test; eksekusi diblok.")
        adapter = self._psql()
        env = adapter.environment_status(check_connection=True)
        if not env.connection_ok:
            state.stage = "REMOTE_UNAVAILABLE"
            state.metadata["resume_target"] = "DB_APPLY"
            self._save(state)
            return AutopilotResult("WARNING", state.stage, "Database belum dapat dijangkau; migration belum dijalankan.", run_id)
        lock = ProjectLock(self.paths.locks, profile.project_id, run_id)
        try:
            lock.acquire()
        except ProjectLockedError as exc:
            return self._failure_handoff(repo, profile, state, str(exc))
        journal = Journal(self.paths.runs / run_id / "journal.jsonl")
        try:
            for op in migrations:
                sql_path = (repo / str(op["path"])).resolve()
                if repo not in sql_path.parents:
                    return self._failure_handoff(repo, profile, state, "Migration path keluar dari repository.")
                sql = sql_path.read_text(encoding="utf-8")
                classification = classify_sql(sql)
                if classification in {"DESTRUCTIVE", "NON_TRANSACTIONAL", "UNKNOWN"}:
                    return self._failure_handoff(
                        repo, profile, state,
                        f"Migration classified {classification}; normal approval tidak cukup.",
                        {"classification": classification, "path": str(op["path"])},
                    )
            state.stage = "DB_APPLYING"
            self._save(state)
            for op in migrations:
                sql_path = repo / str(op["path"])
                entry = journal.before("DB_APPLY", {"path": str(op["path"])})
                result = adapter.apply_file(sql_path, single_transaction=True)
                journal.after(entry, "CLEAR" if result.applied else "ERROR", {"returncode": result.returncode})
                if not result.applied:
                    return self._failure_handoff(
                        repo, profile, state, "Database migration gagal.",
                        {"path": str(op["path"]), "stdout": result.stdout, "stderr": result.stderr},
                    )
            state.stage = "DB_APPLIED"
            state.metadata["db_applied"] = True
            self._save(state)
            test_result = self._run_db_tests(repo, state, operations, profile)
            if test_result:
                return test_result
            state.stage = "DB_VERIFIED"
            state.metadata["db_verified"] = True
            self._save(state)
            state.stage = "HUMAN_QA"
            self._save(state)
            self._sync_control_state(state)
            return AutopilotResult("CLEAR", state.stage, "Database applied dan regression clear; human QA required.", run_id)
        finally:
            lock.release()

    def run_remediation(self, repo: Path, package_path: Path) -> AutopilotResult:
        repo = Path(repo).expanduser().resolve()
        package_path = Path(package_path).expanduser().resolve()
        profile = load_project_profile(repo)
        policy = self._load_policy(repo)
        manifest = inspect_package(package_path)
        if manifest.package_type != "REMEDIATION" or not manifest.run_id:
            dummy = RunState(profile.project_id, manifest.run_id or f"{profile.project_id}-invalid-remediation", "FAILED_SAFE", manifest.milestone)
            return self._failure_handoff(repo, profile, dummy, "File bukan remediation package XP yang valid.")
        try:
            state = self.state_store.load(manifest.run_id)
        except Exception as exc:
            dummy = RunState(profile.project_id, manifest.run_id, "FAILED_SAFE", manifest.milestone)
            return self._failure_handoff(repo, profile, dummy, f"Run target remediation tidak ditemukan: {exc}")
        if state.stage != "WAITING_GPT":
            return self._failure_handoff(repo, profile, state, f"Remediation hanya boleh diterapkan saat WAITING_GPT, bukan {state.stage}.")
        git = GitAdapter(repo)
        current_fp = git.working_fingerprint()
        context = RunContext(
            project_id=profile.project_id,
            stage=state.stage,
            base_fingerprint=current_fp,
            run_id=state.run_id,
            incident_id=state.metadata.get("incident_id"),
            incident_challenge=state.metadata.get("incident_challenge"),
        )
        report = validate_package(manifest, context)
        if report.status != "CLEAR":
            return self._failure_handoff(repo, profile, state, "Remediation tidak cocok dengan incident aktif.", {"reasons": report.reasons})
        run_dir = self.paths.runs / state.run_id
        remediations = run_dir / "remediations"
        remediations.mkdir(parents=True, exist_ok=True)
        stored = remediations / f"{state.metadata.get('incident_id', 'incident')}-{package_path.name}"
        shutil.copy2(package_path, stored)
        staging = run_dir / "staging-remediation"
        backup_root = self.paths.backups / profile.project_id / state.run_id / "remediation"
        lock = ProjectLock(self.paths.locks, profile.project_id, state.run_id)
        try:
            lock.acquire()
        except ProjectLockedError as exc:
            return self._failure_handoff(repo, profile, state, str(exc))
        journal = Journal(run_dir / "journal.jsonl")
        try:
            staged = stage_package(stored, staging)
            preflight = PackageExecutor(repo).preflight(staged)
            if preflight.status != "CLEAR":
                return self._failure_handoff(repo, profile, state, "Preflight remediation gagal.", {"reasons": preflight.reasons})
            entry = journal.before("SOURCE_APPLY", {"remediation": stored.name, "incident": state.metadata.get("incident_id")})
            try:
                result = PackageExecutor(repo).apply(staged, backup_root=backup_root)
            except Exception as exc:
                journal.after(entry, "ERROR", {"message": str(exc)})
                return self._failure_handoff(repo, profile, state, f"Remediation apply gagal: {exc}")
            journal.after(entry, "CLEAR", {"changed_paths": result.changed_paths})
            verify_entry = journal.before("SOURCE_VERIFY", {"after_remediation": True})
            with Spinner("Verifikasi source setelah remediation — layar TIDAK hang"):
                ok, verify_log, warning_status, unknown_warnings = self._verify_source(repo, policy)
            journal.after(verify_entry, "CLEAR" if ok else "ERROR", {"warning_status": warning_status})
            if not ok:
                return self._failure_handoff(repo, profile, state, "Verification setelah remediation masih gagal.", {"verify_log": verify_log, "git_diff": git._run("diff", "--binary", "HEAD", "--", check=False)})
            if warning_status == "WARNING":
                return self._failure_handoff(repo, profile, state, "Remediation menghasilkan warning baru.", {"unknown_warnings": unknown_warnings, "verify_log": verify_log}, outcome="WARNING")
            old_incident = state.metadata.get("incident_id")
            state.metadata["resolved_incident_id"] = old_incident
            state.metadata.pop("incident_id", None)
            state.metadata.pop("incident_challenge", None)
            state.metadata.pop("failure_message", None)
            state.metadata["working_fingerprint"] = git.working_fingerprint()
            state.metadata["warning_status"] = warning_status
            state.stage = "SOURCE_VERIFIED"
            self._save(state)
            remote_result = self._remote_safepoint(repo, state, policy, profile)
            if remote_result:
                return remote_result
            original_manifest = inspect_package(Path(str(state.metadata["package"])))
            db_ops = [op for op in original_manifest.operations if op.get("type") in {"APPLY_DB_MIGRATION", "RUN_SQL_TEST"}]
            if any(op.get("type") == "APPLY_DB_MIGRATION" for op in db_ops):
                state.stage = "DB_APPROVAL_REQUIRED"
                self._save(state)
                return AutopilotResult("CLEAR", state.stage, "Remediation clear; perubahan database kembali menunggu approval.", state.run_id)
            db_result = self._run_db_tests(repo, state, db_ops, profile)
            if db_result:
                return db_result
            state.stage = "HUMAN_QA"
            self._save(state)
            self._sync_control_state(state)
            return AutopilotResult("CLEAR", state.stage, "Remediation clear; lanjut ke human QA.", state.run_id)
        finally:
            lock.release()
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    def record_human_qa(self, repo: Path, run_id: str, *, clear: bool, notes: str = "") -> AutopilotResult:
        from datetime import datetime, timezone
        from .redaction import redact_text

        repo = Path(repo).expanduser().resolve()
        profile = load_project_profile(repo)
        state = self.state_store.load(run_id)
        if state.stage != "HUMAN_QA":
            return self._failure_handoff(repo, profile, state, f"Human QA tidak valid dari state {state.stage}.")
        if not clear:
            state.metadata["human_qa"] = {
                "status": "PROBLEM",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "notes": redact_text(notes),
            }
            self._save(state)
            return self._failure_handoff(
                repo,
                profile,
                state,
                "Human QA menemukan masalah.",
                {"human_qa_notes": redact_text(notes)},
            )
        state.metadata["human_qa"] = {
            "status": "CLEAR",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "notes": redact_text(notes),
        }
        state.stage = "READY_TO_LOCK"
        self._save(state)
        self._sync_control_state(state)
        return AutopilotResult("CLEAR", state.stage, "Human QA clear; pekerjaan siap untuk Final Lock.", run_id)

    def final_lock(self, repo: Path, run_id: str, *, approved: bool) -> AutopilotResult:
        from .checkpoint import CheckpointBuilder, CheckpointContext

        repo = Path(repo).expanduser().resolve()
        profile = load_project_profile(repo)
        policy = self._load_policy(repo)
        state = self.state_store.load(run_id)
        if state.stage != "READY_TO_LOCK":
            return self._failure_handoff(repo, profile, state, f"Final Lock tidak valid dari state {state.stage}.")
        if not approved:
            return AutopilotResult("KNOWN", state.stage, "Final Lock belum disetujui; state tidak berubah.", run_id)

        git = GitAdapter(repo)
        # Freeze the verified source boundary. Human QA may inspect the app, but
        # source must not change after XP verification without a new package/audit.
        safepoint_head = state.metadata.get("safepoint_head")
        current_git = git.state(fetch=False)
        if safepoint_head:
            if current_git.head != safepoint_head or current_git.dirty:
                return self._failure_handoff(
                    repo, profile, state,
                    "Source berubah setelah verification/safepoint; Final Lock diblok sampai perubahan diaudit.",
                    {"expected_head": safepoint_head, "actual_head": current_git.head, "dirty": current_git.dirty},
                )
        else:
            expected_fp = state.metadata.get("working_fingerprint")
            if expected_fp and git.working_fingerprint() != expected_fp:
                return self._failure_handoff(
                    repo, profile, state,
                    "Source berubah setelah verification; Final Lock diblok sampai perubahan diaudit.",
                )

        with Spinner("Final verification berjalan — layar TIDAK hang"):
            ok, verify_log, warning_status, unknown_warnings = self._verify_source(repo, policy)
        if not ok:
            return self._failure_handoff(repo, profile, state, "Final verification gagal sebelum lock.", {"verify_log": verify_log})
        if warning_status == "WARNING":
            return self._failure_handoff(
                repo, profile, state, "Warning baru ditemukan saat Final Lock.",
                {"unknown_warnings": unknown_warnings, "verify_log": verify_log}, outcome="WARNING",
            )

        package_path = Path(str(state.metadata.get("package", "")))
        if package_path.is_file():
            manifest = inspect_package(package_path)
            db_ops = [op for op in manifest.operations if op.get("type") == "RUN_SQL_TEST"]
            if state.metadata.get("db_applied") or state.metadata.get("db_verified"):
                db_result = self._run_db_tests(repo, state, db_ops, profile)
                if db_result:
                    return db_result

        state.stage = "LOCKING"
        self._save(state)
        remote_policy = dict(policy.get("remote_safepoint") or {})
        push = bool(remote_policy.get("enabled", False))
        try:
            safepoint = git.create_safepoint(
                f"chore(xp): lock {state.milestone or state.run_id}",
                push=push,
                remote=str(remote_policy.get("remote", "origin")),
            )
        except AdapterError as exc:
            # Commit locally if remote push failed; do not claim remote lock.
            try:
                safepoint = git.create_safepoint(
                    f"chore(xp): lock {state.milestone or state.run_id}", push=False
                )
            except Exception as local_exc:
                return self._failure_handoff(repo, profile, state, f"Final source safepoint gagal: {local_exc}")
            state.metadata["final_remote_error"] = str(exc)

        checkpoint_dir = self.paths.checkpoints / profile.project_id / run_id
        artifacts = CheckpointBuilder(checkpoint_dir).build(
            CheckpointContext(
                project_id=profile.project_id,
                project_name=profile.name,
                milestone=state.milestone or run_id,
                stage="LOCKED_REMOTE" if safepoint.pushed else "LOCKED_LOCAL",
                evidence={
                    "source_verification": "CLEAR",
                    "warning_status": warning_status,
                    "human_qa": state.metadata.get("human_qa"),
                    "db_applied": state.metadata.get("db_applied", False),
                    "db_verified": state.metadata.get("db_verified", False),
                },
                run_id=run_id,
                commit=safepoint.head,
            ),
            repo=repo,
        )
        state.metadata.update(
            {
                "checkpoint_dir": str(checkpoint_dir),
                "checkpoint_report": str(artifacts.report),
                "source_archive": str(artifacts.source_archive) if artifacts.source_archive else None,
                "final_head": safepoint.head,
            }
        )
        state.stage = "LOCKED_REMOTE" if safepoint.pushed else "LOCKED_LOCAL"
        self._save(state)
        lease_released = self._release_remote_lease(profile, state)
        control_synced = self._sync_control_state(state)
        if self._control_repo() is not None and (not lease_released or not control_synced):
            state.stage = "LOCKED_LOCAL"
            self._save(state)
        return AutopilotResult("CLEAR", state.stage, "Final Lock tercatat dengan checkpoint dan source archive.", run_id)

    def resume(self, repo: Path, run_id: str) -> AutopilotResult:
        """Resume a stored run conservatively after pause/process interruption.

        Safe/idempotent verification may be repeated. Critical operations are
        never blindly rerun; ambiguous DB/source/lock state is handed to GPT.
        """
        from .recovery import RecoveryEngine

        repo = Path(repo).expanduser().resolve()
        profile = load_project_profile(repo)
        policy = self._load_policy(repo)
        state = self.state_store.load(run_id)
        if state.project_id != profile.project_id:
            return self._failure_handoff(repo, profile, state, "Run/project identity mismatch during recovery.")
        journal = Journal(self.paths.runs / run_id / "journal.jsonl")
        decision = RecoveryEngine(journal).inspect(state)

        if decision.status == "RECOVERY_REQUIRED":
            operation = decision.operation or "UNKNOWN"
            subject = "Database" if operation == "DB_APPLY" else "Operasi kritis"
            return self._failure_handoff(
                repo,
                profile,
                state,
                f"{subject} terputus dan tidak akan dijalankan ulang secara buta; audit recovery diperlukan.",
                {"interrupted_operation": operation, "recovery_decision": decision.status},
            )

        if decision.status == "SAFE_RETRY":
            interrupted = journal.interrupted_operation()
            operation = decision.operation
            if operation == "SOURCE_VERIFY":
                with Spinner("Verifikasi source (recovery) berjalan"):
                    ok, verify_log, warning_status, unknown_warnings = self._verify_source(repo, policy)
                if interrupted:
                    journal.after(
                        str(interrupted["entry_id"]),
                        "CLEAR" if ok else "ERROR",
                        {"recovered": True, "warning_status": warning_status},
                    )
                if not ok:
                    return self._failure_handoff(repo, profile, state, "Source verification gagal saat recovery.", {"verify_log": verify_log})
                if warning_status == "WARNING":
                    return self._failure_handoff(
                        repo,
                        profile,
                        state,
                        "Warning baru ditemukan saat recovery.",
                        {"unknown_warnings": unknown_warnings, "verify_log": verify_log},
                        outcome="WARNING",
                    )
                state.stage = "SOURCE_VERIFIED"
                state.metadata["working_fingerprint"] = GitAdapter(repo).working_fingerprint()
                state.metadata["warning_status"] = warning_status
                self._save(state)
                remote_result = self._remote_safepoint(repo, state, policy, profile)
                if remote_result:
                    return remote_result
                package_path = Path(str(state.metadata.get("package", "")))
                manifest = inspect_package(package_path) if package_path.is_file() else None
                db_ops = [op for op in (manifest.operations if manifest else ()) if op.get("type") in {"APPLY_DB_MIGRATION", "RUN_SQL_TEST"}]
                if any(op.get("type") == "APPLY_DB_MIGRATION" for op in db_ops):
                    state.stage = "DB_APPROVAL_REQUIRED"
                    self._save(state)
                    return AutopilotResult("CLEAR", state.stage, "Recovery source clear; perubahan database menunggu approval manusia.", run_id)
                db_result = self._run_db_tests(repo, state, db_ops, profile)
                if db_result:
                    return db_result
                state.stage = "HUMAN_QA"
                self._save(state)
                return AutopilotResult("CLEAR", state.stage, "Recovery selesai; lanjut ke human QA.", run_id)
            return self._failure_handoff(
                repo,
                profile,
                state,
                f"Recovery aman untuk {operation}, tetapi handler belum tersedia; audit GPT diperlukan.",
                {"interrupted_operation": operation},
            )

        # No interrupted journal entry: return or continue only from explicit safe gates.
        if state.stage == "HUMAN_QA":
            return AutopilotResult("CLEAR", state.stage, "Pekerjaan menunggu human QA; tidak ada source/database yang diulang.", run_id)
        if state.stage == "READY_TO_LOCK":
            return AutopilotResult("CLEAR", state.stage, "Pekerjaan siap Final Lock dan menunggu approval manusia.", run_id)
        if state.stage == "WAITING_GPT":
            return AutopilotResult("WARNING", state.stage, "Pekerjaan menunggu hasil audit/remediation GPT.", run_id)
        if state.stage in {"LOCKED_LOCAL", "LOCKED_REMOTE"}:
            return AutopilotResult("KNOWN", state.stage, "Pekerjaan sudah dikunci; tidak ada tindakan yang diulang.", run_id)
        if state.stage == "DB_APPROVAL_REQUIRED":
            return AutopilotResult("CLEAR", state.stage, "Perubahan database masih menunggu approval manusia.", run_id)
        if state.stage == "REMOTE_UNAVAILABLE":
            target = str(state.metadata.get("resume_target", ""))
            if target == "REMOTE_SAFEPOINT":
                return self._remote_safepoint(repo, state, policy, profile) or AutopilotResult(
                    "CLEAR", state.stage, "Remote safepoint berhasil dipulihkan.", run_id
                )
            if target == "REMOTE_LEASE":
                lease_result = self._acquire_remote_lease(profile, state)
                if lease_result:
                    return lease_result
                return self._remote_safepoint(repo, state, policy, profile) or AutopilotResult(
                    "CLEAR", state.stage, "Remote lease pulih; safepoint dipulihkan.", run_id
                )
            if target == "DB_APPLY":
                state.stage = "DB_APPROVAL_REQUIRED"
                state.metadata.pop("resume_target", None)
                self._save(state)
                return AutopilotResult("CLEAR", state.stage, "Koneksi database pulih; migration tetap menunggu approval manusia.", run_id)
            if target == "DB_VERIFICATION":
                if not state.metadata.get("db_applied"):
                    state.stage = "DB_APPROVAL_REQUIRED"
                    state.metadata.pop("resume_target", None)
                    self._save(state)
                    return AutopilotResult("CLEAR", state.stage, "Koneksi database pulih; perubahan database menunggu approval manusia.", run_id)
                package_path = Path(str(state.metadata.get("package", "")))
                manifest = inspect_package(package_path) if package_path.is_file() else None
                db_ops = [op for op in (manifest.operations if manifest else ()) if op.get("type") in {"APPLY_DB_MIGRATION", "RUN_SQL_TEST"}]
                db_result = self._run_db_tests(repo, state, db_ops, profile)
                if db_result:
                    return db_result
                state.stage = "HUMAN_QA"
                self._save(state)
                return AutopilotResult("CLEAR", state.stage, "Verifikasi database pulih; lanjut ke human QA.", run_id)
            return AutopilotResult("WARNING", state.stage, "Koneksi remote/database perlu tersedia sebelum pekerjaan dapat dilanjutkan.", run_id)
        if state.stage == "PAUSED_BY_USER":
            target = str(state.metadata.get("resume_target", ""))
            if target == "DB_APPROVAL_REQUIRED":
                state.stage = "DB_APPROVAL_REQUIRED"
                self._save(state)
                return AutopilotResult("CLEAR", state.stage, "Pekerjaan kembali ke persetujuan database; tidak ada perubahan database yang dijalankan.", run_id)
            return AutopilotResult("KNOWN", state.stage, "Pekerjaan dipause; XP tidak menebak tahap lanjutan.", run_id)
        return self._failure_handoff(
            repo,
            profile,
            state,
            f"State {state.stage} tidak memiliki jalur resume otomatis yang aman.",
        )

