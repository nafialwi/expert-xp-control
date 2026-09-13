from __future__ import annotations

import json
from datetime import datetime, timezone
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .paths import XPPaths


@dataclass(frozen=True)
class EngineLifecycleResult:
    status: str
    version: str
    path: Path


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


    def activate_with_health_check(self, version: str, *, health_check) -> EngineLifecycleResult:
        activated = self.activate_candidate(version)
        previous = self.previous_version()
        if previous is None:
            raise RuntimeError("previous engine version is missing after activation")

        try:
            healthy = bool(health_check(activated.path))
        except Exception:
            self._write_atomic(self._active_file, previous)
            raise

        if healthy:
            return activated

        self._write_atomic(self._active_file, previous)
        return EngineLifecycleResult(
            "ROLLED_BACK",
            previous,
            self.paths.versions / previous,
        )

    def promote_candidate(self, version: str) -> CandidatePromotionReport:
        version = str(version).strip()
        previous = self.active_version()

        pre = self.check_candidate(version)
        if pre.status != "CLEAR":
            return CandidatePromotionReport("BLOCKED", version, previous, pre.checks)

        post_checks: dict[str, str] = {}

        def post_health(path: Path) -> bool:
            report = self._check_installed_path(version, path)
            post_checks.update(report.checks)
            return report.status == "CLEAR"

        result = self.activate_with_health_check(version, health_check=post_health)
        if result.status == "ROLLED_BACK":
            return CandidatePromotionReport("ROLLED_BACK", version, previous, post_checks)

        return CandidatePromotionReport("PROMOTED", version, previous, post_checks)
