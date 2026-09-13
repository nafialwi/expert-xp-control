# XP+-10 V3 — rc18.3 Bootstrap Upgrade Design

**Status:** APPROVED by Qwen ruling relayed by the user on 2026-09-13.

## Problem

Expert Workstation `2.0.0-rc18.3` has an inherited public-upgrade defect:
its built-in `xp upgrade` writes `versions/` and `active-version` under
`<home>` instead of canonical `<home>/.expert-workstation`. The running
legacy process also cannot repair its already-loaded `_upgrade_cmd()` merely
by fetching stable source. Literal `xp upgrade` from an untouched rc18.3
origin is therefore impossible-by-construction.

## Approved architecture

For the one-time rc18.3 -> 2.1.0 transition, the public path is a published,
account-neutral bootstrap installer. From origin >= 2.1.0, `xp upgrade`
continues to be the public EngineLifecycle path.

The bootstrap is stdlib-only, resolves home at runtime, contains no lifecycle
activation implementation, stages the stable candidate, and delegates
candidate install plus validation/activation/health-check/rollback semantics
to XP+ `EngineLifecycle`. It never deletes or overwrites the rc18.3 engine
directory.

## Binding gates B1-B8

- **B1 Thin bootstrap:** no hardcoded account paths; no direct active/previous/
  candidate metadata writes; no `_switch_active_version` or direct
  `activate_candidate`; stable EngineLifecycle owns lifecycle semantics.
- **B2 Interrupt safety:** rerunnable; rc18.3 bytes remain unchanged.
- **B3 In repo:** `tools/xp_rc183_bootstrap.py` and
  `tests/test_rc183_bootstrap.py` ship in the tagged source; release assets
  are checksummed.
- **B4 Step-8 gate:** user-exact bootstrap command on a fresh untouched
  rc18.3 test home, followed by A-RB rollback.
- **B5 Honest docs:** README, CHANGELOG, compatibility matrix,
  upgrade/rollback docs, and release notes explicitly state the rc18.3 defect
  and supported one-time bootstrap path.
- **B6 Stray artifacts:** compatibility audit reports legacy
  `<home>/versions` and `<home>/active-version` only; it never deletes them.
  Cleanup requires explicit user approval.
- **B7 Tag sequencing:** `df1eaec...` remains preserved and untagged. The
  follow-up gate-green commit containing this bootstrap is the only
  `v2.1.0` tag target.
- **B8 Evidence:** bootstrap transcript, rollback proof, regression,
  checksums, docs snippets, real-home immutability, historical probe-home
  confirmation, and stray-path inventory/reproduction.

## Release assets

- `xp-rc183-to-210-bootstrap.py`
- `XP_PLUS_2.1.0_ENGINE.zip`
- `SHA256SUMS.txt`

A user places all three in the same directory and runs:

```bash
python xp-rc183-to-210-bootstrap.py
```

No GitHub account identity is embedded in the bootstrap.

## V4 remediation after the first real Termux execution

V3 stopped before commit or remote mutation and exposed two package-code defects:
the bootstrap process directly imported `xp`, violating strict stdlib-only B1,
and it called `activate_with_health_check(version)` without the required
keyword-only `health_check`.

V4 preserves the approved B1-B8 architecture. Every XP import is moved into a
child interpreter whose `PYTHONPATH` is the extracted/installed stable engine.
Candidate installation delegates to stable `EngineLifecycle.install_candidate`.
Activation delegates to stable
`activate_with_health_check(version, health_check=...)`; the callback delegates
to stable `EngineLifecycle.health_check`. Runtime signature inspection only
adapts whether the bound stable `health_check` accepts zero or one required
positional argument. The bootstrap does not implement lifecycle semantics.



<!-- XP+-10 A-HC HEALTH AUTHORITY RESTORATION -->
## XP+-10 A-HC — lifecycle health authority restoration

Recorded: `2026-09-13T06:55:10.145214+00:00`.

Stable 2.1.0 restores the locked `EngineLifecycle.health_check(version)`
interface. The method returns an audit-ready structured result (`ok` plus
per-check records) and reuses stable primitives for candidate/import integrity,
CLI startup, canonical schema readability, registry/state-v1 readability, and
a no-mutation `xp self-test`.

`activate_with_health_check(..., health_check=None)` keeps test injection
backward-compatible, but production `None` means `self.health_check(version)`.
`xp upgrade`, candidate promotion, and the rc18.3 bootstrap therefore share one
engine-owned health authority. Bootstrap code contains no health semantics.

HC5 also restores two additive locked-plan API surfaces found by the one-time
contract sweep: `EngineCandidate(...)` and `BundleBuilder.compact()/deep()`.
The full sweep is recorded in `docs/XP_PLUS_INTERFACE_CONTRACT_SWEEP.md`.

**Permanent XP+ rule (HC8):** every injectable dependency or callback on a
lifecycle-critical production path must have an engine-provided,
regression-tested production default. Injection is for tests; defaults are for
truth. This rule was established by the XP+-08 V3 candidate-match masking
incident and the XP+-10 missing health-authority incident.
