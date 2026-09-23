from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import uuid

from .capability_registry import LocalCapabilityRegistry
from .hermes_worker import HermesLocalWorker
from .local_qwen import LocalQwenAdapter
from .lightweight_worker import LightweightLocalWorker
from .project_service import ProjectService
from .planner import BoundedReadOnlyPlanner
from .runtime import XPRuntime
from .sandbox_review import ReviewBundle
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
from .visual_gateway import make_visual_gateway
from .work_flow import WorkFlowNeedsAttention, prepare_work
from .work_session_service import WorkSessionService
from .zero_cost_e2e import (
    HumanApproval,
    HumanReviewDecision,
    ReviewAction,
    ZeroCostE2EService,
)


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

    work = sub.add_parser("work", help="Human-friendly reviewed local work flow")
    work.add_argument("--goal", default=None, help="Pekerjaan yang ingin dilakukan")
    work.add_argument("--project", dest="project_id", default=None)
    work.add_argument("--worker-prompt", default=None)
    work.add_argument("--verify-cmd", default=None)
    work.add_argument("--verify-timeout", type=float, default=120.0)
    work.add_argument("--backend", choices=["lightweight_local", "hermes"], default=None)
    worker_decision = work.add_mutually_exclusive_group()
    worker_decision.add_argument("--confirm-worker", action="store_true")
    worker_decision.add_argument("--decline-worker", action="store_true")
    sandbox_decision = work.add_mutually_exclusive_group()
    sandbox_decision.add_argument("--approve-sandbox", action="store_true")
    sandbox_decision.add_argument("--decline-sandbox", action="store_true")
    review_decision = work.add_mutually_exclusive_group()
    review_decision.add_argument("--apply", action="store_true")
    review_decision.add_argument("--discard", action="store_true")
    work.add_argument("--job-id", default=None)
    work.add_argument("--json", action="store_true", dest="json_output")
    work.add_argument("--qwen-base-url", default="http://127.0.0.1:8080")
    work.add_argument("--qwen-model", default="local")
    work.add_argument("--qwen-timeout", type=float, default=120.0)
    work.add_argument("--hermes-binary", default=None)
    work.add_argument("--hermes-base-url", default="http://127.0.0.1:18085/v1")
    work.add_argument("--hermes-model", default="local")
    work.add_argument("--hermes-context-length", type=int, default=65536)
    work.add_argument("--hermes-timeout", type=float, default=480.0)

    visual = sub.add_parser(
        "visual-gateway",
        help="Development-only loopback PWA gateway",
    )
    visual.add_argument("--host", default="127.0.0.1")
    visual.add_argument("--port", type=int, default=8765)
    visual.add_argument("--static-root", type=Path, default=None)
    visual.add_argument("--qwen-base-url", default="http://127.0.0.1:8080")
    visual.add_argument("--qwen-model", default="local")
    visual.add_argument("--qwen-timeout", type=float, default=120.0)
    visual.add_argument("--hermes-binary", default=None)
    visual.add_argument(
        "--hermes-base-url",
        default="http://127.0.0.1:18085/v1",
    )
    visual.add_argument("--hermes-model", default="local")
    visual.add_argument("--hermes-context-length", type=int, default=65536)
    visual.add_argument("--hermes-timeout", type=float, default=480.0)

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


def _build_local_workers(args: argparse.Namespace) -> dict[str, object]:
    return {
        "lightweight_local": LightweightLocalWorker(),
        "hermes": HermesLocalWorker(
            binary=getattr(args, "hermes_binary", None),
            base_url=getattr(
                args,
                "hermes_base_url",
                "http://127.0.0.1:18085/v1",
            ),
            model=getattr(args, "hermes_model", "local"),
            context_length=int(
                getattr(args, "hermes_context_length", 65536)
            ),
            timeout=float(getattr(args, "hermes_timeout", 480.0)),
        ),
    }


def _worker_command(args: argparse.Namespace) -> int:
    if args.worker_command != "choose":
        raise AssertionError("unreachable")

    prompt = _load_worker_prompt(args)
    resources = ResourceSnapshot.probe_local_linux()
    workers = _build_local_workers(args)
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



def _work_goal(args: argparse.Namespace) -> str | None:
    if args.goal is not None:
        value = str(args.goal).strip()
        return value or None
    if sys.stdin.isatty():
        value = input("Pekerjaan apa yang ingin dilakukan? ").strip()
        return value or None
    return None


def _work_worker_approval(args: argparse.Namespace) -> bool | None:
    if args.confirm_worker:
        return True
    if args.decline_worker:
        return False
    if sys.stdin.isatty():
        answer = input("Gunakan worker di atas? [1=ya / 0=batal]: ").strip()
        if answer == "1":
            return True
        if answer == "0":
            return False
    return None


def _work_sandbox_approval(args: argparse.Namespace) -> bool | None:
    if args.approve_sandbox:
        return True
    if args.decline_sandbox:
        return False
    if sys.stdin.isatty():
        answer = input("Izinkan eksekusi hanya di sandbox terisolasi? [1=ya / 0=batal]: ").strip()
        if answer == "1":
            return True
        if answer == "0":
            return False
    return None


def _work_review_action(args: argparse.Namespace, bundle: ReviewBundle) -> ReviewAction | None:
    if args.json_output:
        _print({"review": bundle.as_dict()})
    else:
        print()
        print(bundle.render_text())
        print()
    if args.apply:
        return ReviewAction.APPLY
    if args.discard:
        return ReviewAction.DISCARD
    if sys.stdin.isatty():
        answer = input("Keputusan review [1=Apply / 0=Discard]: ").strip()
        if answer == "1":
            return ReviewAction.APPLY
        if answer == "0":
            return ReviewAction.DISCARD
    return None


def _work_command(args: argparse.Namespace) -> int:
    goal = _work_goal(args)
    if not goal:
        print(
            "Deskripsi pekerjaan belum diberikan. Gunakan --goal atau jalankan secara interaktif.",
            file=sys.stderr,
        )
        return 3

    with XPRuntime.open(args.home) as runtime:
        projects = ProjectService(runtime.store)
        try:
            prepared = prepare_work(
                projects,
                goal=goal,
                project_id=args.project_id,
                worker_prompt=args.worker_prompt,
                verifier_command=args.verify_cmd,
                verifier_timeout=args.verify_timeout,
            )
        except WorkFlowNeedsAttention as exc:
            print(f"Perlu perhatian: {exc}", file=sys.stderr)
            return 2

        if args.json_output:
            _print({"work": prepared.as_dict()})
        else:
            print("XP Next — Work")
            print()
            print(f"Project: {prepared.project_name} ({prepared.project_id})")
            print(f"Pekerjaan: {prepared.goal}")
            print(
                "Verifier: "
                + " ".join(prepared.verifier.argv)
                + f" [{prepared.verifier_source}]"
            )
            print()

        workers = _build_local_workers(args)
        selector = WorkerSelector(workers)
        request = WorkerSelectionRequest(
            worker_prompt=prepared.worker_prompt,
            requested_backend=args.backend,
        )
        selection = selector.select(
            request,
            resources=ResourceSnapshot.probe_local_linux(),
        )
        if args.json_output:
            _print({"selection": selection.as_dict()})
        else:
            print(render_worker_choice(selection))

        if selection.status is SelectionStatus.NEEDS_ATTENTION:
            return 2

        approved_worker = _work_worker_approval(args)
        if approved_worker is None:
            print(
                "Konfirmasi worker belum diberikan. Gunakan --confirm-worker atau --decline-worker.",
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
                approved=approved_worker,
            ),
            resources=ResourceSnapshot.probe_local_linux(),
        )
        if args.json_output:
            _print({"confirmation": confirmation.as_dict()})
        else:
            print()
            print(render_worker_confirmation(confirmation))

        if confirmation.status is ConfirmationStatus.DECLINED:
            return 4
        if confirmation.status is not ConfirmationStatus.CONFIRMED:
            return 2

        sandbox_approval = _work_sandbox_approval(args)
        if sandbox_approval is None:
            print(
                "Persetujuan sandbox belum diberikan. Gunakan --approve-sandbox atau --decline-sandbox.",
                file=sys.stderr,
            )
            return 3
        if not sandbox_approval:
            if not args.json_output:
                print("Pekerjaan dibatalkan sebelum sandbox dijalankan.")
            return 4

        if not sys.stdin.isatty() and not (args.apply or args.discard):
            print(
                "Keputusan review belum diberikan. Gunakan --apply atau --discard.",
                file=sys.stderr,
            )
            return 3

        def decide(bundle: ReviewBundle) -> HumanReviewDecision:
            action = _work_review_action(args, bundle)
            if action is None:
                raise WorkFlowNeedsAttention("keputusan Apply/Discard belum diberikan")
            return HumanReviewDecision(
                action=action,
                approved_change_fingerprint=bundle.change_fingerprint,
            )

        worker = workers[confirmation.backend_id]
        service = ZeroCostE2EService(
            store=runtime.store,
            projects=projects,
            paths=runtime.paths,
            reasoner=LocalQwenAdapter(
                base_url=args.qwen_base_url,
                model=args.qwen_model,
                timeout=args.qwen_timeout,
            ),
            planner=BoundedReadOnlyPlanner(),
            worker=worker,
        )
        job_id = args.job_id or f"work-{uuid.uuid4().hex[:12]}"
        try:
            result = service.run(
                job_id=job_id,
                project_id=prepared.project_id,
                goal=prepared.goal,
                worker_prompt=prepared.worker_prompt,
                verifier_specs=(prepared.verifier,),
                sandbox_write_approval=HumanApproval(granted=True),
                review_decider=decide,
                worker_selection=selection,
                worker_confirmation=confirmation,
            )
        except WorkFlowNeedsAttention as exc:
            print(f"Perlu perhatian: {exc}", file=sys.stderr)
            return 2

        if args.json_output:
            _print({"result": result.as_dict()})
        else:
            print()
            print(f"Hasil akhir: {result.job_state}")
            print(f"Job: {result.job_id}")
            print(f"Worker: {result.worker_status}")
            print(f"Review: {result.review_status or '-'}")
            print(f"Apply/Discard: {result.apply_status or '-'}")
            if result.recovery_ref:
                print(f"Recovery: {result.recovery_ref}")

        if result.job_state == "COMPLETED":
            return 0
        if result.job_state == "CANCELLED":
            return 4
        return 2

def _visual_gateway_command(args: argparse.Namespace) -> int:
    workers = _build_local_workers(args)

    static_root = args.static_root

    with XPRuntime.open(args.home) as runtime:
        projects = ProjectService(runtime.store)
        selector = WorkerSelector(workers)
        service = WorkSessionService(
            store=runtime.store,
            projects=projects,
            paths=runtime.paths,
            reasoner=LocalQwenAdapter(
                base_url=args.qwen_base_url,
                model=args.qwen_model,
                timeout=args.qwen_timeout,
            ),
            planner=BoundedReadOnlyPlanner(),
            workers=workers,
            selector=selector,
        )
        server = make_visual_gateway(
            host=args.host,
            port=args.port,
            service=service,
            static_root=static_root,
        )
        bound_host = str(server.server_address[0])
        bound_port = int(server.server_address[1])
        display_host = (
            f"[{bound_host}]" if ":" in bound_host else bound_host
        )
        print(
            "XP Next Visual Gateway: "
            f"http://{display_host}:{bound_port}"
        )
        print("Mode: loopback-only / development")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    return 0


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
    if args.command == "work":
        return _work_command(args)
    if args.command == "visual-gateway":
        return _visual_gateway_command(args)
    if args.command == "project":
        return _project_command(args)
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
