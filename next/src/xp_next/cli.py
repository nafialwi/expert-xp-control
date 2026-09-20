from __future__ import annotations

import argparse
import json
from pathlib import Path

from .capability_registry import LocalCapabilityRegistry
from .project_service import ProjectService
from .runtime import XPRuntime
from .service import build_project_context, doctor, status, version
from .task_contract import TaskIntentKind


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


def _project_command(args: argparse.Namespace) -> int:
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
    if args.command == "project":
        return _project_command(args)
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
