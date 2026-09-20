from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3
import sys

from . import __version__
from .capability_registry import LocalCapabilityRegistry
from .project_service import ProjectService
from .local_qwen import LocalQwenAdapter
from .reasoning import ReasoningRequest, compact_reasoning_context
from .runtime import XPRuntime
from .task_contract import TaskIntent, TaskIntentKind


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
            "phase": "CP-04A",
            "runtime": "LOCAL_STATE_ACTIVE",
            "ai": "LOCAL_READ_ONLY_ADAPTER",
            "worker": "NOT_INTEGRATED",
            "database": "READY",
            "project_count": len(listed),
            "active_project": active,
            "active_project_inspection": inspection,
            "local_capabilities": capabilities,
            "network_required": False,
            "network_probe_performed": False,
        }


def build_project_context(
    home: Path | str | None,
    *,
    goal: str,
    intent: TaskIntentKind,
    project_id: str | None = None,
) -> dict[str, object]:
    capabilities = LocalCapabilityRegistry().snapshot()
    task = TaskIntent.read_only(goal=goal, kind=intent)
    with XPRuntime.open(home) as runtime:
        projects = ProjectService(runtime.store)
        return projects.context(
            task=task,
            capabilities=capabilities,
            project_id=project_id,
        )


def doctor() -> dict[str, object]:
    return {
        "python": "READY" if sys.version_info >= (3, 11) else "UNAVAILABLE",
        "sqlite": "READY" if sqlite3.sqlite_version_info else "UNAVAILABLE",
        "git": "READY" if shutil.which("git") else "UNAVAILABLE",
        "network_probe_performed": False,
    }


def reason_project_context(
    home: Path | str | None,
    *,
    goal: str,
    intent: TaskIntentKind,
    project_id: str | None = None,
    base_url: str = "http://127.0.0.1:8080",
    model: str = "local",
    max_tokens: int = 128,
    timeout: float = 120.0,
) -> dict[str, object]:
    context = build_project_context(
        home,
        goal=goal,
        intent=intent,
        project_id=project_id,
    )
    request = ReasoningRequest(
        task=TaskIntent.read_only(goal=goal, kind=intent),
        context=compact_reasoning_context(context),
        max_tokens=max_tokens,
    )
    adapter = LocalQwenAdapter(base_url=base_url, model=model, timeout=timeout)
    readiness = adapter.readiness()
    if not readiness.ready:
        return {
            "readiness": readiness.as_dict(),
            "result": None,
        }
    result = adapter.reason(request)
    return {
        "readiness": readiness.as_dict(),
        "result": result.as_dict(),
    }
