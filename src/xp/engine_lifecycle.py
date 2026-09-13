from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .paths import XPPaths


@dataclass(frozen=True)
class EngineCandidate:
    version: str
    path: Path
    status: str


@dataclass(frozen=True)
class HealthCheckRecord:
    code: str
    status: str
    detail: str


@dataclass(frozen=True)
class EngineHealthReport:
    ok: bool
    version: str
    checks: tuple[HealthCheckRecord, ...]

    @property
    def status(self) -> str:
        return "CLEAR" if self.ok else "BLOCKED"

    def status_map(self) -> dict[str, str]:
        return {item.code: item.status for item in self.checks}


@dataclass(frozen=True)
class EngineLifecycleResult:
    status: str
    version: str
    path: Path
    health: EngineHealthReport | None = None


@dataclass(frozen=True)
class CandidateHealthReport:
    status: str
    version: str
    checks: dict[str, str]


@dataclass(frozen=True)
class CandidatePromotionReport:
    status: str
    version: str
    previous_version: str | None
    checks: dict[str, str]


class EngineLifecycle:
    """Install, validate, activate, and roll back XP engine candidates safely."""

    def __init__(self, home: Path):
        self.home = Path(home).expanduser().resolve()
        self.paths = XPPaths.from_home(self.home)
        self.paths.ensure_runtime_dirs()
        self._active_file = self.paths.root / "active-version"
        self._previous_file = self.paths.root / "previous-version"
        self._candidate_file = self.paths.root / "candidate-version"

    @staticmethod
    def _read_version(path: Path) -> str | None:
        if not path.is_file():
            return None
        value = path.read_text(encoding="utf-8").strip()
        return value or None

    @staticmethod
    def _write_atomic(path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".xp-{os.getpid()}.tmp")
        tmp.write_text(value + "\n", encoding="utf-8")
        os.replace(tmp, path)

    def active_version(self) -> str | None:
        return self._read_version(self._active_file)

    def previous_version(self) -> str | None:
        return self._read_version(self._previous_file)

    def candidate_version(self) -> str | None:
        return self._read_version(self._candidate_file)

    def install_candidate(self, version: str, source: Path) -> EngineLifecycleResult:
        version = str(version).strip()
        if not version or "/" in version or "\\" in version or version in {".", ".."}:
            raise ValueError("invalid engine candidate version")

        source = Path(source).expanduser().resolve()
        package_init = source / "src" / "xp" / "__init__.py"
        if not package_init.is_file():
            raise ValueError("candidate source must contain src/xp/__init__.py")

        destination = self.paths.versions / version
        if destination.exists():
            raise FileExistsError(f"engine candidate already exists: {version}")

        shutil.copytree(source, destination)
        self._write_atomic(self._candidate_file, version)
        return EngineLifecycleResult("INSTALLED", version, destination)

    @staticmethod
    def _safe_env(src_dir: Path, home: Path) -> dict[str, str]:
        env = os.environ.copy()
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(src_dir) + (os.pathsep + existing if existing else "")
        env["XP_USER_HOME"] = str(home)
        return env

    def _check_installed_path(self, version: str, destination: Path) -> CandidateHealthReport:
        src_dir = destination / "src"
        if not (src_dir / "xp" / "__init__.py").is_file():
            return CandidateHealthReport("BLOCKED", version, {"install-shape": "BLOCKED"})

        env = self._safe_env(src_dir, self.home)
        checks: dict[str, str] = {}

        try:
            imported = subprocess.run(
                [sys.executable, "-c", "import xp; print(xp.__version__)"],
                cwd=destination,
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            imported = None
        checks["import"] = (
            "CLEAR"
            if imported is not None
            and imported.returncode == 0
            and imported.stdout.strip() == version
            else "BLOCKED"
        )

        try:
            cli = subprocess.run(
                [sys.executable, "-m", "xp.cli", "version"],
                cwd=destination,
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            cli = None
        checks["cli-version"] = (
            "CLEAR"
            if cli is not None
            and cli.returncode == 0
            and version in cli.stdout
            else "BLOCKED"
        )

        compat_test = destination / "tests" / "test_backward_compatibility.py"
        if compat_test.is_file():
            try:
                compat = subprocess.run(
                    [sys.executable, "-m", "unittest", "tests.test_backward_compatibility", "-v"],
                    cwd=destination,
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=60,
                )
            except (OSError, subprocess.TimeoutExpired):
                compat = None
            checks["compat-v1"] = (
                "CLEAR"
                if compat is not None and compat.returncode == 0
                else "BLOCKED"
            )
        else:
            checks["compat-v1"] = "BLOCKED"

        status = "CLEAR" if all(value == "CLEAR" for value in checks.values()) else "BLOCKED"
        return CandidateHealthReport(status, version, checks)

    def check_candidate(self, version: str) -> CandidateHealthReport:
        version = str(version).strip()
        candidate = self.candidate_version()
        if candidate != version:
            raise ValueError(
                f"candidate mismatch: expected {candidate or '-'}, got {version or '-'}"
            )
        return self._check_installed_path(version, self.paths.versions / version)

    def _switch_active_version(self, version: str) -> EngineLifecycleResult:
        version = str(version).strip()
        candidate = version
        destination = self.paths.versions / version
        if not (destination / 'src' / 'xp' / '__init__.py').is_file():
            raise FileNotFoundError(f'engine candidate is incomplete: {version}')
        current = self.active_version()
        if current is None:
            raise RuntimeError('active engine version is missing')
        self._write_atomic(self._previous_file, current)
        self._write_atomic(self._active_file, version)
        try:
            self._candidate_file.unlink()
        except FileNotFoundError:
            pass
        return EngineLifecycleResult('ACTIVATED', version, destination)

    def activate_candidate(self, version: str):
        candidate = self.candidate_version()
        if candidate != version:
            raise ValueError(
                f"candidate mismatch: expected {candidate or '-'}, got {version or '-'}"
            )
        return self._switch_active_version(version)


    def _record_rollback(self, version: str, *, reason: str):
        journal = self.paths.root / "engine-rollback-journal.jsonl"
        event = {
            "version": str(version),
            "reason": str(reason or "manual rollback"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        existing = journal.read_text(encoding="utf-8") if journal.is_file() else ""
        tmp = journal.with_name(journal.name + f".{os.getpid()}.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(existing)
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(json.dumps(event, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, journal)
        return event

    def rollback_to_previous(self, *, reason: str = "manual rollback"):
        previous = self.previous_version()
        if not previous:
            raise RuntimeError("previous engine version is not available")
        target = self.paths.versions / previous
        if not target.is_dir():
            raise FileNotFoundError(
                f"previous installed engine directory not found: {previous}"
            )
        departed = self.active_version()
        if not departed:
            raise RuntimeError("active engine version is not available")

        result = self._switch_active_version(previous)

        if self.candidate_version() is not None:
            raise RuntimeError("candidate marker was not cleared after rollback")
        self._record_rollback(departed, reason=reason)
        return result


    @staticmethod
    def _engine_tree_hash(root: Path) -> str:
        digest = hashlib.sha256()
        root = Path(root)
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if (
                ".git" in path.parts
                or "__pycache__" in path.parts
                or path.suffix == ".pyc"
            ):
                continue
            if not path.is_file():
                continue
            digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def _health_json_child(
        self,
        destination: Path,
        code: str,
        *,
        timeout: int = 60,
        extra_env: dict[str, str] | None = None,
    ) -> tuple[bool, str]:
        env = self._safe_env(destination / "src", self.home)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if extra_env:
            env.update(extra_env)
        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=destination,
                env=env,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"child execution failed: {exc}"
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "child returned nonzero").strip()
            return False, detail[-1000:]
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            return False, "child returned no structured result"
        try:
            payload = json.loads(lines[-1])
        except json.JSONDecodeError as exc:
            return False, f"child JSON decode failed: {exc}"
        return bool(payload.get("ok")), str(payload.get("detail") or "")

    def health_check(self, version: str) -> EngineHealthReport:
        """Run the production post-activation health authority for one engine version."""
        version = str(version).strip()
        destination = self.paths.versions / version
        records: list[HealthCheckRecord] = []

        active_ok = self.active_version() == version
        records.append(
            HealthCheckRecord(
                "active-version",
                "CLEAR" if active_ok else "BLOCKED",
                f"active={self.active_version() or '-'}; expected={version or '-'}",
            )
        )

        preflight = self._check_installed_path(version, destination)
        import_ok = (
            preflight.checks.get("install-shape") != "BLOCKED"
            and preflight.checks.get("import") == "CLEAR"
        )
        records.append(
            HealthCheckRecord(
                "candidate-import-integrity",
                "CLEAR" if import_ok else "BLOCKED",
                f"stable primitive: {preflight.checks}",
            )
        )
        cli_ok = preflight.checks.get("cli-version") == "CLEAR"
        records.append(
            HealthCheckRecord(
                "cli-startup",
                "CLEAR" if cli_ok else "BLOCKED",
                f"stable primitive cli-version={preflight.checks.get('cli-version', 'missing')}",
            )
        )
        compat_pre_ok = preflight.checks.get("compat-v1") == "CLEAR"
        records.append(
            HealthCheckRecord(
                "compat-v1-preflight",
                "CLEAR" if compat_pre_ok else "BLOCKED",
                f"stable primitive compat-v1={preflight.checks.get('compat-v1', 'missing')}",
            )
        )

        schema_code = (
            "import json\n"
            "from xp.schema import schema_for\n"
            "schema=schema_for('work')\n"
            "ok=isinstance(schema, dict) and schema.get('schema_name') == 'work'\n"
            "print(json.dumps({'ok': ok, 'detail': 'schema_for(work) readable'}))\n"
        )
        schema_ok, schema_detail = self._health_json_child(destination, schema_code)
        records.append(
            HealthCheckRecord(
                "schema-reader",
                "CLEAR" if schema_ok else "BLOCKED",
                schema_detail or "schema reader failed",
            )
        )

        fixtures = destination / "tests" / "fixtures"
        compatibility_code = (
            "import json, os\n"
            "from pathlib import Path\n"
            "from xp.compatibility import CompatibilityAudit\n"
            "target=Path(os.environ['XP_HEALTH_FIXTURES'])\n"
            "report=CompatibilityAudit(Path(os.environ['XP_USER_HOME'])).run(target)\n"
            "checks={item.code:item.status for item in report.checks}\n"
            "ok=(report.status == 'CLEAR' and report.read_only "
            "and checks.get('STATE_V1') == 'CLEAR' and checks.get('REGISTRY_V1') == 'CLEAR')\n"
            "detail='status=%s read_only=%s STATE_V1=%s REGISTRY_V1=%s' % "
            "(report.status, report.read_only, checks.get('STATE_V1'), checks.get('REGISTRY_V1'))\n"
            "print(json.dumps({'ok': ok, 'detail': detail}))\n"
        )
        compatibility_ok, compatibility_detail = self._health_json_child(
            destination,
            compatibility_code,
            extra_env={"XP_HEALTH_FIXTURES": str(fixtures)},
        )
        records.append(
            HealthCheckRecord(
                "registry-state-readability",
                "CLEAR" if compatibility_ok else "BLOCKED",
                compatibility_detail or "compatibility reader failed",
            )
        )

        before_hash = self._engine_tree_hash(destination) if destination.is_dir() else ""
        env = self._safe_env(destination / "src", self.home)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            self_test = subprocess.run(
                [sys.executable, "-m", "xp.cli", "self-test"],
                cwd=destination,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired):
            self_test = None
        after_hash = self._engine_tree_hash(destination) if destination.is_dir() else ""
        self_test_ok = (
            self_test is not None
            and self_test.returncode == 0
            and bool(before_hash)
            and before_hash == after_hash
        )
        self_test_detail = (
            "self-test exit=0; candidate bytes unchanged"
            if self_test_ok
            else "self-test failed or candidate bytes changed"
        )
        records.append(
            HealthCheckRecord(
                "no-mutation-self-test",
                "CLEAR" if self_test_ok else "BLOCKED",
                self_test_detail,
            )
        )

        ok = all(item.status == "CLEAR" for item in records)
        return EngineHealthReport(ok=ok, version=version, checks=tuple(records))

    def activate_with_health_check(
        self,
        version: str,
        *,
        health_check=None,
    ) -> EngineLifecycleResult:
        activated = self.activate_candidate(version)
        previous = self.previous_version()
        if previous is None:
            raise RuntimeError("previous engine version is missing after activation")

        report = None
        try:
            if health_check is None:
                report = self.health_check(version)
                healthy = report.ok
            else:
                outcome = health_check(activated.path)
                report = outcome if isinstance(outcome, EngineHealthReport) else None
                healthy = outcome.ok if report is not None else bool(outcome)
        except Exception:
            self.rollback_to_previous(reason="post-activation-health-exception")
            raise

        if healthy:
            return EngineLifecycleResult(
                "ACTIVATED",
                version,
                activated.path,
                report,
            )

        rollback = self.rollback_to_previous(reason="post-activation-health-failed")
        return EngineLifecycleResult(
            "ROLLED_BACK",
            rollback.version,
            rollback.path,
            report,
        )

    def promote_candidate(self, version: str) -> CandidatePromotionReport:
        version = str(version).strip()
        previous = self.active_version()

        pre = self.check_candidate(version)
        if pre.status != "CLEAR":
            return CandidatePromotionReport("BLOCKED", version, previous, pre.checks)

        result = self.activate_with_health_check(version)
        post_checks = result.health.status_map() if result.health is not None else {}
        if result.status == "ROLLED_BACK":
            return CandidatePromotionReport("ROLLED_BACK", version, previous, post_checks)

        return CandidatePromotionReport("PROMOTED", version, previous, post_checks)
