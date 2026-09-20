from __future__ import annotations
import shutil
import sqlite3
import sys
from . import __version__

def version() -> dict[str, object]:
    return {"product": "XP Next", "version": __version__}

def status() -> dict[str, object]:
    return {
        "product": "XP Next",
        "version": __version__,
        "phase": "CP-01B",
        "runtime": "SKELETON_ONLY",
        "ai": "NOT_INTEGRATED",
        "worker": "NOT_INTEGRATED",
        "database": "STATE_STORE_IMPLEMENTED_NOT_ACTIVATED",
        "network_required": False,
    }

def doctor() -> dict[str, object]:
    return {
        "python": "READY" if sys.version_info >= (3, 11) else "UNAVAILABLE",
        "sqlite": "READY" if sqlite3.sqlite_version_info else "UNAVAILABLE",
        "git": "READY" if shutil.which("git") else "UNAVAILABLE",
        "network_probe_performed": False,
    }
