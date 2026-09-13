# Expert Workstation (XP)

Framework untuk membangun project dengan disiplin checkpoint, verifikasi otomatis, dan audit trail.

## Visi

XP adalah "rumah" untuk project-project Anda. AI mengirim blueprint deklaratif, XP execute dengan safety gates. Hasilnya: milestone terkunci dengan bukti yang bisa diverifikasi kapan pun.

## Fitur

- Checkpoint System (arsip permanen milestone)
- 8 Gate Verification (lint, test, build, dll)
- Atomic Apply (rollback jika gagal)
- Remote Lease (koordinasi multi-device)
- Human QA (gerbang manual)
- Incident Handling (auto rollback + handoff)
- Bundle Export (pindah AI session)

## Quick Start

### Install

    curl -fsSL https://raw.githubusercontent.com/nafialwi/expert-xp-control/xp-engine/installer.sh | sh

### Mulai

    xp help

## Dokumentasi

- [Quick Start](docs/quickstart.md)
- [Workflow](docs/workflow.md)
- [Commands](docs/commands.md)
- [Concepts](docs/concepts.md)
- [Project Setup](docs/project-setup.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Architecture](docs/architecture.md)

## Branch di Repo Ini

- main — control-repo state (lease management XP, jangan di-touch)
- xp-engine — source XP + dokumentasi + installer (branch publik untuk install)

## Lisensi

MIT

## XP+ Universal Acceptance (XP+-07)

XP+-07 provides a reusable promotion harness for the seven categories in the
FINAL LOCK acceptance matrix: Plain Git, Node, Python, Node+PostgreSQL,
Firebase/static web, Segeran Jiwa POS Legacy, and Segeran Jiwa POS Next.

Generic fixture tests:

```bash
PYTHONPATH=src python -m unittest tests.test_acceptance_fixtures -v
```

Legacy/Next compatibility smoke is explicitly local-copy/read-only and requires
explicit local repository paths:

```bash
XP07_LEGACY_REPO=/path/to/legacy \
XP07_NEXT_REPO=/path/to/next \
XP07_REAL_HOME="$HOME" \
PYTHONPATH=src python -m unittest tests.test_real_project_contracts -v
```

The real-project smoke replaces source/control remotes with temporary local Git
remotes before running workflow gates, strips production database/cloud
credentials, blocks PostgreSQL apply/test methods, requires production
deployment to remain disabled, and hard-fails on source mutation.

This harness is intended to be re-run as a promotion gate at XP+-09.


### A+ read-only proof

XP+-07 V4 uses two separate evidence zones. Zone 1 hashes every byte-addressable
entry in the original Legacy/Next repository trees, including `.git` and ignored
artifacts, and forbids subprocess/project execution inside those originals.
Zone 2 runs all realistic verification/workflow activity on physical temporary
copies and measures the same canonical source boundary XP itself protects:
HEAD, tracked diff, non-ignored untracked content, plus an explicit `.xp/`
integrity check. Git-ignored build/cache/runtime changes are informational only
and each changed ignored path is validated through Git ignore rules. The harness
adds no silent ignore exclusions.
