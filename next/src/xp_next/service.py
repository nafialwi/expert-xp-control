from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3
import sys

from . import __version__
from .capability_registry import LocalCapabilityRegistry
from .project_service import ProjectService
from .local_qwen import LocalQwenAdapter
from .planner import BoundedReadOnlyPlanner, verify_plan
from .reasoning import ReasoningRequest, ReasoningResult, ReasoningStatus, compact_reasoning_context
from .sandbox_review import VerifierSpec, build_review_bundle
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
            "phase": "CP-07A",
            "runtime": "LOCAL_STATE_ACTIVE",
            "ai": "LOCAL_READ_ONLY_ADAPTER",
            "worker": "LOCAL_HERMES_ISOLATED_ADAPTER",
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


def _reason_from_context(
    *,
    context: dict[str, object],
    task: TaskIntent,
    base_url: str,
    model: str,
    max_tokens: int,
    timeout: float,
) -> dict[str, object]:
    request = ReasoningRequest(
        task=task,
        context=compact_reasoning_context(context),
        max_tokens=max_tokens,
    )
    adapter = LocalQwenAdapter(
        base_url=base_url,
        model=model,
        timeout=timeout,
    )
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
    task = TaskIntent.read_only(goal=goal, kind=intent)
    return _reason_from_context(
        context=context,
        task=task,
        base_url=base_url,
        model=model,
        max_tokens=max_tokens,
        timeout=timeout,
    )

def build_read_only_plan(
    home: Path | str | None,
    *,
    goal: str,
    intent: TaskIntentKind,
    project_id: str | None = None,
    base_url: str = "http://127.0.0.1:8080",
    model: str = "local",
    max_tokens: int = 96,
    timeout: float = 120.0,
) -> dict[str, object]:
    context = build_project_context(
        home,
        goal=goal,
        intent=intent,
        project_id=project_id,
    )
    task = TaskIntent.read_only(goal=goal, kind=intent)
    reasoning_bundle = _reason_from_context(
        context=context,
        task=task,
        base_url=base_url,
        model=model,
        max_tokens=max_tokens,
        timeout=timeout,
    )

    raw_result = reasoning_bundle.get("result")
    if isinstance(raw_result, dict):
        reasoning = ReasoningResult(
            status=ReasoningStatus(str(raw_result["status"])),
            output=str(raw_result.get("output", "")),
            backend_id=str(raw_result.get("backend_id", "local_qwen")),
            model=str(raw_result.get("model", model)),
            transport=str(raw_result.get("transport", "loopback_http")),
            external_network_used=bool(raw_result.get("external_network_used")),
            detail=str(raw_result.get("detail", "")),
        )
    else:
        readiness = reasoning_bundle.get("readiness")
        detail = ""
        if isinstance(readiness, dict):
            detail = str(readiness.get("detail", "reasoning backend unavailable"))
        reasoning = ReasoningResult(
            status=ReasoningStatus.NEEDS_ATTENTION,
            output="",
            backend_id="local_qwen",
            model=model,
            transport="loopback_http",
            external_network_used=False,
            detail=detail or "reasoning backend unavailable",
        )

    plan = BoundedReadOnlyPlanner().build(
        task=task,
        context=compact_reasoning_context(context),
        reasoning=reasoning,
    )
    ok, detail = verify_plan(plan)
    return {
        "context": compact_reasoning_context(context),
        "reasoning": reasoning_bundle,
        "plan": plan.as_dict(),
        "verification": {"ok": ok, "detail": detail},
    }


def review_sandbox(
    project_root: Path | str,
    *,
    verifier_specs: tuple[VerifierSpec, ...] = (),
    max_diff_chars: int = 12_000,
) -> dict[str, object]:
    bundle = build_review_bundle(
        project_root,
        verifier_specs=verifier_specs,
        max_diff_chars=max_diff_chars,
    )
    return {
        "bundle": bundle.as_dict(),
        "human_review": bundle.render_text(),
    }
