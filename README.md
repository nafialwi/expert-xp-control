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


## XP+ 2.1.0-rc1 Release Candidate

XP+ keeps the executable name `xp`, project metadata under `.xp/`, package
prefix `XP_PKG_*`, and profile/state/protocol version 1 compatibility.

### A+ two-zone read-only proof

**Zone 1** protects the original Legacy/Next repositories with full-tree byte
immutability, including `.git` and ignored artifacts; no project command runs
inside the originals. **Zone 2** runs realistic verify/workflow activity on a
physical temporary copy and protects the canonical XP source boundary: expected
HEAD, tracked diff, non-ignored untracked content, and `.xp/` explicitly.
Changed Git-ignored build/cache artifacts are informational and must resolve
through committed Git ignore rules.

The XP+-09 compatibility matrix must include separate **Zone 1 proof** and
**Zone 2 proof** columns.

### Generic Toolchain Adapter

The Generic Toolchain Adapter is user-approved for XP+ 2.1.0 as an
**optional-only** capability. Project Doctor / Smart Onboarding must never
auto-select it without explicit user approval. Its regression suite locks the
argv allow-list, `shell=False`, bounded timeout, declared purpose, repo-path
scope, sensitive-environment withholding, output redaction, network/deploy
blocking, and source-mutation guard. Built-in adapter signatures remain
unchanged. Full handshake and compatibility-matrix documentation is finalized
at XP+-09/XP+-10.

<!-- XP+-10 RC18.3 BOOTSTRAP KNOWN LIMITATION -->
## XP+ 2.1.0 — rc18.3 one-time upgrade limitation

Recorded: `2026-09-13T06:55:10.142751+00:00`.

The rc18.3 built-in `xp upgrade` is defective: it writes `versions/` and
`active-version` outside the canonical `.expert-workstation` state root.
It can therefore print an upgrade-success message while canonical
`active-version` remains `2.0.0-rc18.3`.

The supported one-time path from rc18.3 to XP+ 2.1.0 is the published
`xp-rc183-to-210-bootstrap.py` release asset together with
`XP_PLUS_2.1.0_ENGINE.zip` and `SHA256SUMS.txt`. The bootstrap is stdlib-only
and delegates lifecycle validation/activation/health-check/rollback semantics
to XP+ `EngineLifecycle`; it does not implement a second activation path.

For origin >= 2.1.0, `xp upgrade` remains the supported EngineLifecycle public
update path.

Legacy `<home>/active-version` and `<home>/versions` outside the canonical XP
root are a **REPORT-ONLY** compatibility finding. XP and the bootstrap never
delete them automatically; cleanup requires explicit user approval.
