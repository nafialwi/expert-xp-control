# XP+-08 XP+ Release Candidate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce and shadow-test XP+ `2.1.0-rc1` side-by-side while leaving the real active engine at `2.0.0-rc18.3`.

**Architecture:** Brand the candidate source as XP+ without changing the `xp`, `.xp/`, registry, profile/state/protocol-v1 identities. Commit the RC source locally after full source regression, install that exact clean source through `EngineLifecycle`, then run self-test, fixture acceptance, A+ Legacy/Next shadow smoke, identity-surface checks, and a rollback drill on a physical copy of `~/.expert-workstation`. Only push after every RC gate passes.

**Tech Stack:** Python 3 standard library, Git, existing XP EngineLifecycle, XP+-07 A+ acceptance harness, Termux.

**Spec:** `XP_PLUS_BLUEPRINT_v1.0_FINAL_LOCK.md` plus Qwen XP+-08 authorization R2-R8.

## Global Constraints

- Product display is `XP+`; executable remains `xp`.
- RC engine version is exactly `2.1.0-rc1`.
- Real active engine remains exactly `2.0.0-rc18.3`.
- Candidate install is side-by-side through `EngineLifecycle`; no direct activation of the real home.
- `.xp/`, `XP_PKG_*`, registry identity, profile v1, state v1 and protocol v1 remain unchanged.
- Generic Toolchain Adapter is optional-only; Smart Onboarding must never auto-select it.
- Nine Generic Toolchain security guards remain locked by regression tests.
- XP+-07 A+ Zone 1/Zone 2 semantics remain authoritative.
- Real-home rollback drill is forbidden at XP+-08; drill only a copy of `~/.expert-workstation`.
- GitHub push occurs only after candidate artifact gates pass.

---

### Task 1: RC identity surface and schema handshake

**Files:**
- Modify: `src/xp/__init__.py`
- Modify: `src/xp/ui.py`
- Modify: `src/xp/cli.py`
- Create: `scripts/render_handshake_schema.py`
- Modify: `docs/handshake.md`
- Test: `tests/test_rc_identity_surface.py`

**Interfaces:**
- `xp.__version__ == "2.1.0-rc1"`
- `xp.PRODUCT_NAME == "XP+"`
- `xp.CLI_NAME == "xp"`
- handshake schema block equals `schema_for(work|remediation|project-profile)`.

- [ ] Write identity tests first.
- [ ] Run them and require RED from missing RC brand/version/generated schema block.
- [ ] Apply minimal brand/version changes.
- [ ] Regenerate handshake block from canonical schema.
- [ ] Run identity tests GREEN.

### Task 2: RC documentation and frozen contracts

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Test: `tests/test_rc_identity_surface.py`
- Existing: `tests/test_generic_toolchain_qwen_guards.py`

- [ ] Document A+ Zone 1 and Zone 2 definition.
- [ ] Document Generic Toolchain Adapter as user-approved optional-only capability.
- [ ] Record that XP+-09 compatibility matrix must include Zone 1 / Zone 2 proof columns.
- [ ] Run identity + Generic Toolchain guard tests.

### Task 3: Source regression and local RC commit

- [ ] Run full unittest discovery.
- [ ] Run compileall and `git diff --check`.
- [ ] Confirm `STATE_VERSION`, `profile_version`, and `PROTOCOL_VERSION` remain v1.
- [ ] Commit `chore(xp+): prepare 2.1.0-rc1`.
- [ ] Do not push yet.

### Task 4: Side-by-side RC candidate installation

**Files:**
- Create: `scripts/rc_lifecycle_gate.py`

- [ ] Snapshot real `active-version`, `previous-version`, and `~/bin/xp`.
- [ ] Install committed RC source through `EngineLifecycle.install_candidate`.
- [ ] Assert real active remains `2.0.0-rc18.3`.
- [ ] Assert installed candidate reports `2.1.0-rc1`.
- [ ] Assert `~/bin/xp` unchanged and no new `xp+` executable is created.

### Task 5: Shadow-test installed candidate artifact

- [ ] Run candidate `xp.cli version` and UI banner; require XP+ / `2.1.0-rc1`.
- [ ] Run candidate self-test in isolated XP_USER_HOME.
- [ ] Run candidate universal fixture suite.
- [ ] Run candidate A+ boundary suite.
- [ ] Run candidate Generic Toolchain nine-guard suite.
- [ ] Run candidate identity-surface suite.
- [ ] Run candidate `scripts/compat-smoke.py` against Legacy and Next originals with candidate `PYTHONPATH`.
- [ ] Validate candidate real-project contract from captured A+ evidence.

### Task 6: Copy-home rollback drill

- [ ] Copy `~/.expert-workstation` physically to a temporary user home.
- [ ] Use the installed candidate artifact's `EngineLifecycle` to activate `2.1.0-rc1` only in the copied home.
- [ ] Assert copied `previous-version == 2.0.0-rc18.3`.
- [ ] Force `rollback_to_previous()`.
- [ ] Assert copied active engine returns to `2.0.0-rc18.3`.
- [ ] Read real copied registry and checkpoint history after rollback.

### Task 7: Final gate and GitHub sync

- [ ] Reconfirm real active engine and real `xp` wrapper unchanged.
- [ ] Reconfirm installed candidate still exists side-by-side.
- [ ] Push the local RC commit.
- [ ] Print R2-R8 evidence.


## V4 A-RB Architecture Ruling — Binding

- `activate_candidate()` preserves candidate-match guard.
- `rollback_to_previous()` is a separate entry point for a trusted previously-installed version.
- Both share one private `_switch_active_version()` primitive using temp files + `os.replace`.
- Rollback sets `previous-version` to the version departed (the RC), clears candidate marker, and atomically appends an audit event `{version, reason, timestamp}`.
- Lifecycle integration regressions execute the real switch path; no activation mocking is permitted.
- Copy-home acceptance must prove registry/checkpoint readability after rollback.
