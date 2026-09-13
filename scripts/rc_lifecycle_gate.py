#!/usr/bin/env python3
from __future__ import annotations

import argparse
import inspect
import json
import shutil
from pathlib import Path


RC_VERSION = "2.1.0-rc1"
BASE_VERSION = "2.0.0-rc18.3"


def make_lifecycle(home: Path):
    from xp.engine_lifecycle import EngineLifecycle
    from xp.paths import XPPaths

    home = Path(home).expanduser().resolve()
    attempts = []

    factories = [
        lambda: EngineLifecycle(home),
        lambda: EngineLifecycle(XPPaths.from_home(home)),
    ]
    for factory in factories:
        try:
            lifecycle = factory()
            # Probe a read-only method to ensure constructor shape is correct.
            lifecycle.active_version()
            return lifecycle
        except Exception as exc:
            attempts.append(f"{type(exc).__name__}: {exc}")

    raise RuntimeError(
        "EngineLifecycle constructor could not be resolved: "
        + " | ".join(attempts)
    )


def candidate_path(home: Path, result=None) -> Path:
    if result is not None:
        path = getattr(result, "path", None)
        if path:
            return Path(path).expanduser().resolve()
    return (
        Path(home).expanduser().resolve()
        / ".expert-workstation"
        / "versions"
        / RC_VERSION
    )


def install(home: Path, source: Path) -> dict:
    home = Path(home).expanduser().resolve()
    source = Path(source).expanduser().resolve()
    lifecycle = make_lifecycle(home)

    before = lifecycle.active_version()
    if before != BASE_VERSION:
        raise RuntimeError(
            f"real active engine must stay {BASE_VERSION}; found {before}"
        )

    result = lifecycle.install_candidate(RC_VERSION, source)
    after = lifecycle.active_version()
    if after != BASE_VERSION:
        raise RuntimeError(
            "side-by-side install changed active engine: "
            f"{before} -> {after}"
        )

    reported = (
        lifecycle.candidate_version()
        if hasattr(lifecycle, "candidate_version")
        else RC_VERSION
    )
    if reported != RC_VERSION:
        raise RuntimeError(
            f"candidate_version mismatch: {reported}"
        )

    path = candidate_path(home, result)
    if not (path / "src" / "xp" / "__init__.py").is_file():
        raise RuntimeError(
            f"installed candidate artifact incomplete: {path}"
        )

    return {
        "active_before": before,
        "active_after": after,
        "candidate_version": reported,
        "candidate_path": str(path),
    }


def _call_reader(reader, path: Path):
    import json as _json

    try:
        return reader(path)
    except (TypeError, AttributeError):
        return reader(
            _json.loads(path.read_text(encoding="utf-8"))
        )


def drill(home: Path) -> dict:
    home = Path(home).expanduser().resolve()
    lifecycle = make_lifecycle(home)

    start = lifecycle.active_version()
    if start != BASE_VERSION:
        raise RuntimeError(
            f"copy-home drill must start at {BASE_VERSION}; found {start}"
        )

    lifecycle.activate_candidate(RC_VERSION)
    active_candidate = lifecycle.active_version()
    previous = lifecycle.previous_version()

    if active_candidate != RC_VERSION:
        raise RuntimeError(
            f"candidate activation failed: {active_candidate}"
        )
    if previous != BASE_VERSION:
        raise RuntimeError(
            f"previous-version must record {BASE_VERSION}; found {previous}"
        )

    lifecycle.rollback_to_previous(reason="xp08-copy-home-drill")
    rolled_back = lifecycle.active_version()
    previous_after_rollback = lifecycle.previous_version()
    candidate_after_rollback = lifecycle.candidate_version()

    if rolled_back != BASE_VERSION:
        raise RuntimeError(
            f"forced rollback failed: active={rolled_back}"
        )
    if previous_after_rollback != RC_VERSION:
        raise RuntimeError(
            "post-rollback previous-version must be the departed RC: "
            f"{previous_after_rollback}"
        )
    if candidate_after_rollback is not None:
        raise RuntimeError(
            "candidate marker must be cleared after rollback: "
            f"{candidate_after_rollback}"
        )

    journal = (
        home
        / ".expert-workstation"
        / "engine-rollback-journal.jsonl"
    )
    if not journal.is_file():
        raise RuntimeError("rollback audit journal missing")
    audit_rows = [
        json.loads(line)
        for line in journal.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not audit_rows:
        raise RuntimeError("rollback audit journal empty")
    rollback_event = audit_rows[-1]
    if rollback_event.get("version") != RC_VERSION:
        raise RuntimeError(
            f"rollback audit version mismatch: {rollback_event}"
        )
    if rollback_event.get("reason") != "xp08-copy-home-drill":
        raise RuntimeError(
            f"rollback audit reason mismatch: {rollback_event}"
        )
    if not rollback_event.get("timestamp"):
        raise RuntimeError(
            f"rollback audit timestamp missing: {rollback_event}"
        )

    # Real registry must remain readable after rollback.
    from xp.project_registry import ProjectRegistry

    projects = ProjectRegistry.for_home(home).list_projects()
    if not projects:
        raise RuntimeError(
            "copy-home registry became unreadable/empty after rollback"
        )

    # Existing checkpoint history must remain v1-readable.
    from xp.checkpoint import read_checkpoint_state_v1

    checkpoints_root = (
        home
        / ".expert-workstation"
        / "checkpoints"
    )
    checkpoint_files = sorted(
        checkpoints_root.glob("*/*/CHECKPOINT_STATE.json")
    )
    if not checkpoint_files:
        raise RuntimeError(
            "copy-home checkpoint history missing"
        )

    readable = 0
    for path in checkpoint_files:
        _call_reader(read_checkpoint_state_v1, path)
        readable += 1

    return {
        "start_active": start,
        "candidate_active": active_candidate,
        "previous_version": previous,
        "rolled_back_active": rolled_back,
        "previous_after_rollback": previous_after_rollback,
        "candidate_after_rollback": candidate_after_rollback,
        "rollback_audit": rollback_event,
        "registry_projects_readable": len(projects),
        "checkpoints_readable": readable,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    install_parser = sub.add_parser("install")
    install_parser.add_argument("--home", required=True)
    install_parser.add_argument("--source", required=True)

    drill_parser = sub.add_parser("drill")
    drill_parser.add_argument("--home", required=True)

    args = parser.parse_args()

    if args.command == "install":
        result = install(Path(args.home), Path(args.source))
    else:
        result = drill(Path(args.home))

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
