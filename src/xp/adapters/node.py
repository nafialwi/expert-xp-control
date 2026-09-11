from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .base import CapabilityAdapter


class BoundedCommandError(ValueError):
    pass


class NodeAdapter(CapabilityAdapter):
    def __init__(self, repo: Path):
        self.repo = Path(repo)
        package_path = self.repo / "package.json"
        if not package_path.exists():
            raise BoundedCommandError("package.json not found")
        data = json.loads(package_path.read_text(encoding="utf-8"))
        self.scripts = set((data.get("scripts") or {}).keys())

    def capabilities(self) -> set[str]:
        return {"node-environment", "npm-script"}

    def resolve_script(self, script: str) -> list[str]:
        if script not in self.scripts:
            raise BoundedCommandError(f"npm script not declared: {script}")
        return ["npm", "run", script]

    def run_script(self, script: str, timeout: int = 1800) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.resolve_script(script),
            cwd=self.repo,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
