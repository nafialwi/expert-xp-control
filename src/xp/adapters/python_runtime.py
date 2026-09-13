from __future__ import annotations

import subprocess
from pathlib import Path

from .base import AdapterReadiness, CapabilityAdapter


class BoundedCommandError(ValueError):
    pass


class PythonAdapter(CapabilityAdapter):
    def __init__(self, repo: Path | None = None, allowed_modules: set[str] | None = None):
        self.repo = Path(repo) if repo is not None else None
        self.allowed_modules = set(allowed_modules or {"unittest"})

    def capabilities(self) -> set[str]:
        return {"python-environment", "python-module"}

    def readiness(self) -> AdapterReadiness:
        import shutil
        python_bin = shutil.which("python")
        if python_bin is None:
            return AdapterReadiness(
                False,
                "NOT_READY",
                "python executable not found",
                tuple(sorted(self.capabilities())),
            )
        if self.repo is not None and not self.repo.exists():
            return AdapterReadiness(
                False,
                "NOT_READY",
                "repository path does not exist",
                tuple(sorted(self.capabilities())),
            )
        return AdapterReadiness(
            True,
            "READY",
            "Python runtime is locally available.",
            tuple(sorted(self.capabilities())),
            {"allowed_modules": sorted(self.allowed_modules)},
        )

    def resolve_module(self, module: str, args: list[str] | None = None) -> list[str]:
        if module not in self.allowed_modules:
            raise BoundedCommandError(f"python module not allowed: {module}")
        return ["python", "-m", module, *(args or [])]

    def run_module(self, module: str, args: list[str] | None = None, timeout: int = 1800) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.resolve_module(module, args),
            cwd=self.repo,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
