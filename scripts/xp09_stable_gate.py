#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def make_lifecycle(home: Path):
    from xp.engine_lifecycle import EngineLifecycle
    from xp.paths import XPPaths

    home = Path(home).expanduser().resolve()
    attempts = []
    for factory in (
        lambda: EngineLifecycle(home),
        lambda: EngineLifecycle(XPPaths.from_home(home)),
    ):
        try:
            lifecycle = factory()
            lifecycle.active_version()
            return lifecycle
        except Exception as exc:
            attempts.append(f"{type(exc).__name__}: {exc}")
    raise RuntimeError(
        "EngineLifecycle constructor unresolved: " + " | ".join(attempts)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--baseline-source', required=True)
    parser.add_argument('--stable-version', required=True)
    parser.add_argument('--base-version', required=True)
    args = parser.parse_args()

    home = Path(args.home).expanduser().resolve()
    source = Path(args.source).expanduser().resolve()
    baseline = Path(args.baseline_source).expanduser().resolve()
    stable = args.stable_version
    base = args.base_version

    if not (baseline / 'src' / 'xp' / '__init__.py').is_file():
        raise RuntimeError('baseline engine source is incomplete')
    if not (source / 'src' / 'xp' / '__init__.py').is_file():
        raise RuntimeError('stable projection source is incomplete')

    from xp.paths import XPPaths
    paths = XPPaths.from_home(home)
    paths.ensure_runtime_dirs()

    base_target = paths.versions / base
    if base_target.exists():
        shutil.rmtree(base_target)
    shutil.copytree(baseline, base_target, symlinks=True)

    (paths.root / 'active-version').write_text(base + '\n', encoding='utf-8')
    (paths.root / 'previous-version').unlink(missing_ok=True)
    (paths.root / 'candidate-version').unlink(missing_ok=True)

    lifecycle = make_lifecycle(home)
    lifecycle.install_candidate(stable, source)
    installed = paths.versions / stable
    if not installed.is_dir():
        raise RuntimeError('stable candidate did not install side-by-side')
    if lifecycle.active_version() != base:
        raise RuntimeError('candidate install changed active version')
    if lifecycle.candidate_version() != stable:
        raise RuntimeError('candidate marker mismatch after install')

    lifecycle.activate_candidate(stable)
    if lifecycle.active_version() != stable:
        raise RuntimeError('stable candidate activation failed')
    if lifecycle.previous_version() != base:
        raise RuntimeError('promotion did not preserve rc18.3 as previous')
    if lifecycle.candidate_version() is not None:
        raise RuntimeError('candidate marker not cleared after promotion')

    lifecycle.rollback_to_previous(reason='xp09-stable-projection-drill')
    if lifecycle.active_version() != base:
        raise RuntimeError('rollback did not restore rc18.3')
    if lifecycle.previous_version() != stable:
        raise RuntimeError('rollback did not record departed stable version')
    if lifecycle.candidate_version() is not None:
        raise RuntimeError('candidate marker not cleared after rollback')

    journal = paths.root / 'engine-rollback-journal.jsonl'
    rows = [
        json.loads(line)
        for line in journal.read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    if not rows:
        raise RuntimeError('rollback journal missing evidence')
    event = rows[-1]
    if event.get('version') != stable:
        raise RuntimeError(f'rollback audit version mismatch: {event}')
    if event.get('reason') != 'xp09-stable-projection-drill':
        raise RuntimeError(f'rollback audit reason mismatch: {event}')
    if not event.get('timestamp'):
        raise RuntimeError(f'rollback audit timestamp missing: {event}')

    print(json.dumps({
        'base_version': base,
        'stable_version': stable,
        'installed_candidate_path': str(installed),
        'active_after_rollback': lifecycle.active_version(),
        'previous_after_rollback': lifecycle.previous_version(),
        'candidate_after_rollback': lifecycle.candidate_version(),
        'rollback_audit': event,
    }, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
