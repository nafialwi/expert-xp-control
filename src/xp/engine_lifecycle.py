from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .paths import XPPaths


@dataclass(frozen=True)
class EngineLifecycleResult:
    status: str
    version: str
    path: Path


class EngineLifecycle:
    """Manage XP engine candidates and activation metadata safely."""

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

        return EngineLifecycleResult(
            status="INSTALLED",
            version=version,
            path=destination,
        )

    def activate_candidate(self, version: str) -> EngineLifecycleResult:
        version = str(version).strip()
        candidate = self.candidate_version()
        if candidate != version:
            raise ValueError(
                f"candidate mismatch: expected {candidate or '-'}, got {version or '-'}"
            )

        destination = self.paths.versions / version
        if not (destination / "src" / "xp" / "__init__.py").is_file():
            raise FileNotFoundError(f"engine candidate is incomplete: {version}")

        current = self.active_version()
        if current is None:
            raise RuntimeError("active engine version is missing")

        # Preserve rollback origin before switching the active pointer.
        self._write_atomic(self._previous_file, current)
        self._write_atomic(self._active_file, version)

        # Candidate marker is no longer needed after successful pointer switch.
        try:
            self._candidate_file.unlink()
        except FileNotFoundError:
            pass

        return EngineLifecycleResult(
            status="ACTIVATED",
            version=version,
            path=destination,
        )

    def activate_with_health_check(
        self,
        version: str,
        *,
        health_check,
    ) -> EngineLifecycleResult:
        activated = self.activate_candidate(version)
        previous = self.previous_version()
        if previous is None:
            raise RuntimeError("previous engine version is missing after activation")

        try:
            healthy = bool(health_check(activated.path))
        except Exception:
            # The candidate is already active at this point. Restore the known
            # previous version before propagating the original health-check error.
            self._write_atomic(self._active_file, previous)
            raise

        if healthy:
            return activated

        # A negative health result is also unsafe: restore the previous engine.
        self._write_atomic(self._active_file, previous)
        return EngineLifecycleResult(
            status="ROLLED_BACK",
            version=previous,
            path=self.paths.versions / previous,
        )
