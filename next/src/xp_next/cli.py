from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .capability_registry import LocalCapabilityRegistry
from .hermes_worker import HermesLocalWorker
from .lightweight_worker import LightweightLocalWorker
from .project_service import ProjectService
from .runtime import XPRuntime
from .service import build_project_context, build_read_only_plan, doctor, reason_project_context, status, version
from .task_contract import TaskIntentKind
from .worker_selection import (
    ConfirmationStatus,
    HumanWorkerConfirmation,
    ResourceSnapshot,
    SelectionStatus,
    WorkerSelectionRequest,
    WorkerSelector,
    confirm_worker_selection,
)
from .worker_ui import render_worker_choice, render_worker_confirmation


def _print(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xp-next")
    parser.add_argument(
        "--home",
        type=Path,
        default=None,
        help="XP Next runtime home (default: XP_NEXT_HOME or ~/.xp-next)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version")
    sub.add_parser("status")
    sub.add_parser("doctor")
    sub.add_parser("capabilities")

    worker = sub.add_parser("worker")
    worker_sub = worker.add_subparsers(dest="worker_command", required=True)
    choose = worker_sub.add_parser("choose")
    prompt_group = choose.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument(
        "--prompt",
        help="Explicit worker prompt or CP-08D JSON operation.",
    )
    prompt_group.add_argument(
        "--prompt-file",
        type=Path,
        help="Read the worker prompt from a local UTF-8 file.",
    )
    choose.add_argument(
        "--backend",
        choices=["lightweight_local", "hermes"],
        default=None,
        help="Request one exact worker instead of asking XP for a recommendation.",
    )
    decision = choose.add_mutually_exclusive_group()
    decision.add_argument(
        "--confirm",
        action="store_true",
        help="Explicitly confirm the displayed worker.",
    )
    decision.add_argument(
        "--decline",
        action="store_true",
        help="Explicitly decline the displayed worker.",
    )
    choose.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit structured JSON instead of the human-readable view.",
    )
    choose.add_argument(
        "--hermes-binary",
        default=None,
        help="Optional Hermes executable override.",
    )
    choose.add_argument(
        "--hermes-base-url",
        default="http://127.0.0.1:18085/v1",
        help="Loopback Hermes model endpoint.",
    )
    choose.add_argument(
        "--hermes-model",
        default="local",
        help="Hermes local model identifier.",
    )

    project = sub.add_parser("project")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_sub.add_parser("list")
    project_sub.add_parser("current")

    inspect = project_sub.add_parser("inspect")
    inspect.add_argument("project_id", nargs="?", default=None)

    context = project_sub.add_parser("context")
    context.add_argument("--goal", required=True)
    context.add_argument(
        "--intent",
        choices=["inspect", "analyze", "explain"],
        default="inspect",
    )
    context.add_argument("project_id", nargs="?", default=None)

    reason = project_sub.add_parser("reason")
    reason.add_argument("--goal", required=True)
    reason.add_argument(
        "--intent",
        choices=["inspect", "analyze", "explain"],
        default="analyze",
    )
    reason.add_argument("--base-url", default="http://127.0.0.1:8080")
    reason.add_argument("--model", default="local")
    reason.add_argument("--max-tokens", type=int, default=128)
    reason.add_argument("--timeout", type=float, default=120.0)
    reason.add_argument("project_id", nargs="?", default=None)

    plan = project_sub.add_parser("plan")
    plan.add_argument("--goal", required=True)
    plan.add_argument(
        "--intent",
        choices=["inspect", "analyze", "explain"],
        default="analyze",
    )
    plan.add_argument("--base-url", default="http://127.0.0.1:8080")
    plan.add_argument("--model", default="local")
    plan.add_argument("--max-tokens", type=int, default=96)
    plan.add_argument("--timeout", type=float, default=120.0)
    plan.add_argument("project_id", nargs="?", default=None)

    register = project_sub.add_parser("register")
    register.add_argument("--id", required=True)
    register.add_argument("--name", required=True)
    register.add_argument("--root", type=Path, required=True)
    register.add_argument(
        "--source-kind",
        choices=["local", "git"],
        default="local",
    )

    switch = project_sub.add_parser("switch")
    switch.add_argument("project_id")
    return parser


def _load_worker_prompt(args: argparse.Namespace) -> str:
    if args.prompt is not None:
        return str(args.prompt)
    path = Path(args.prompt_file).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError("worker prompt file must be a regular file")
    if path.stat().st_size > 12_000:
        raise ValueError("worker prompt file exceeds 12000-byte CLI limit")
    return path.read_text(encoding="utf-8")


def _worker_command(args: argparse.Namespace) -> int:
    if args.worker_command != "choose":
        raise AssertionError("unreachable")

    prompt = _load_worker_prompt(args)
    resources = ResourceSnapshot.probe_local_linux()
    workers = {
        "lightweight_local": LightweightLocalWorker(),
        "hermes": HermesLocalWorker(
            binary=args.hermes_binary,
            base_url=args.hermes_base_url,
            model=args.hermes_model,
        ),
    }
    selector = WorkerSelector(workers)
    request = WorkerSelectionRequest(
        worker_prompt=prompt,
        requested_backend=args.backend,
    )
    selection = selector.select(request, resources=resources)

    if args.json_output:
        _print({"selection": selection.as_dict()})
    else:
        print(render_worker_choice(selection))

    if selection.status is SelectionStatus.NEEDS_ATTENTION:
        return 2

    approved: bool | None
    if args.confirm:
        approved = True
    elif args.decline:
        approved = False
    elif sys.stdin.isatty():
        answer = input("Pilihan: ").strip()
        if answer == "1":
            approved = True
        elif answer == "0":
            approved = False
        else:
            print("Pilihan tidak dikenal; worker tidak dijalankan.", file=sys.stderr)
            return 2
    else:
        if not args.json_output:
            print(
                "Konfirmasi belum diberikan. Jalankan lagi dengan --confirm "
                "atau --decline.",
                file=sys.stderr,
            )
        return 3

    assert selection.backend_id is not None
    confirmation = confirm_worker_selection(
        selector,
        selection=selection,
        request=request,
        confirmation=HumanWorkerConfirmation(
            backend_id=selection.backend_id,
            approved=approved,
        ),
        resources=ResourceSnapshot.probe_local_linux(),
    )

    if args.json_output:
        _print({"confirmation": confirmation.as_dict()})
    else:
        print()
        print(render_worker_confirmation(confirmation))

    if confirmation.status is ConfirmationStatus.CONFIRMED:
        return 0
    if confirmation.status is ConfirmationStatus.DECLINED:
        return 4
    return 2


def _project_command(args: argparse.Namespace) -> int:
    if args.project_command == "plan":
        intent = TaskIntentKind(args.intent.upper())
        _print(
            build_read_only_plan(
                args.home,
                goal=args.goal,
                intent=intent,
                project_id=args.project_id,
                base_url=args.base_url,
                model=args.model,
                max_tokens=args.max_tokens,
                timeout=args.timeout,
            )
        )
        return 0

    if args.project_command == "reason":
        intent = TaskIntentKind(args.intent.upper())
        _print(
            reason_project_context(
                args.home,
                goal=args.goal,
                intent=intent,
                project_id=args.project_id,
                base_url=args.base_url,
                model=args.model,
                max_tokens=args.max_tokens,
                timeout=args.timeout,
            )
        )
        return 0

    if args.project_command == "context":
        intent = TaskIntentKind(args.intent.upper())
        _print(
            {
                "context": build_project_context(
                    args.home,
                    goal=args.goal,
                    intent=intent,
                    project_id=args.project_id,
                )
            }
        )
        return 0

    with XPRuntime.open(args.home) as runtime:
        projects = ProjectService(runtime.store)
        if args.project_command == "list":
            _print({"projects": projects.list_projects()})
            return 0
        if args.project_command == "current":
            _print({"project": projects.current()})
            return 0
        if args.project_command == "inspect":
            _print({"inspection": projects.inspect(args.project_id)})
            return 0
        if args.project_command == "register":
            _print(
                {
                    "project": projects.register(
                        args.id,
                        args.name,
                        args.root,
                        source_kind=args.source_kind,
                    )
                }
            )
            return 0
        if args.project_command == "switch":
            _print({"project": projects.switch(args.project_id)})
            return 0
    raise AssertionError("unreachable")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "version":
        _print(version())
        return 0
    if args.command == "status":
        _print(status(args.home))
        return 0
    if args.command == "doctor":
        _print(doctor())
        return 0
    if args.command == "capabilities":
        _print({"capabilities": LocalCapabilityRegistry().snapshot()})
        return 0
    if args.command == "worker":
        return _worker_command(args)
    if args.command == "project":
        return _project_command(args)
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
