from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3
import sys

from . import __version__
from .capability_registry import LocalCapabilityRegistry
from .project_service import ProjectService
from .runtime import XPRuntime


def version() -> dict[str, object]:
    return {"product": "XP Next", "version": __version__}


def status(home: Path | str | None = None) -> dict[str, object]:
    capabilities = LocalCapabilityRegistry().snapshot()
    with XPRuntime.open(home) as runtime:
        projects = ProjectService(runtime.store)
        listed = projects.list_projects()
        active = projects.current()
        inspection = projects.inspect() if active is not None else None
        return {
            "product": "XP Next",
            "version": __version__,
            "phase": "CP-02B",
            "runtime": "LOCAL_STATE_ACTIVE",
            "ai": "NOT_INTEGRATED",
            "worker": "NOT_INTEGRATED",
            "database": "READY",
            "project_count": len(listed),
            "active_project": active,
            "active_project_inspection": inspection,
            "local_capabilities": capabilities,
            "network_required": False,
            "network_probe_performed": False,
        }


def doctor() -> dict[str, object]:
    return {
        "python": "READY" if sys.version_info >= (3, 11) else "UNAVAILABLE",
        "sqlite": "READY" if sqlite3.sqlite_version_info else "UNAVAILABLE",
        "git": "READY" if shutil.which("git") else "UNAVAILABLE",
        "network_probe_performed": False,
    }
