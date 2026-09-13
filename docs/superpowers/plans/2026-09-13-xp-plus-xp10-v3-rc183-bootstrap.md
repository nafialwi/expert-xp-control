# XP+-10 V3 rc18.3 Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add and release the approved one-time rc18.3 -> XP+ 2.1.0 bootstrap without changing A-RB lifecycle semantics or the user's real active engine.

**Architecture:** The bootstrap is a stdlib-only release tool that verifies sibling release assets, stages the stable source through the stable lifecycle install API, then invokes the installed stable EngineLifecycle health-check activation path. A report-only compatibility audit detects the inherited legacy stray paths. The final tag points to the follow-up commit containing bootstrap, tests, audit, and honest documentation.

**Tech Stack:** Python standard library, unittest, Git, GitHub CLI, ZIP/SHA256.

**Spec:** `docs/superpowers/specs/2026-09-13-xp-plus-rc183-bootstrap-design.md`

## Global Constraints

- Stable version remains `2.1.0`.
- Base evidence commit `df1eaecad1abd498bc0fdaf583ba095e353775b5` is not amended or tagged.
- Real active XP remains `2.0.0-rc18.3` during XP+-10.
- No production DB/deploy action.
- No force push or admin review bypass.
- Bootstrap never deletes/overwrites rc18.3.
- Bootstrap never directly implements activation/rollback semantics.

---

### Task 1: RED tests for bootstrap and report-only audit

**Files:**
- Create: `tests/test_rc183_bootstrap.py`
- Create: `tests/test_xp10_bootstrap_docs.py`

- [ ] Copy tests before production files.
- [ ] Run the focused suite and require RED because bootstrap/audit/docs are absent.

### Task 2: Bootstrap + report-only compatibility audit

**Files:**
- Create: `tools/xp_rc183_bootstrap.py`
- Create: `src/xp/compatibility_audit.py`
- Modify: `src/xp/readiness.py`

- [ ] Implement stdlib-only asset verification and safe extraction.
- [ ] Stage via stable `EngineLifecycle.install_candidate`.
- [ ] Delegate activation/health-check to installed stable `EngineLifecycle.activate_with_health_check`.
- [ ] Add interruption/rerun regression.
- [ ] Add report-only stray finding to `xp audit`.
- [ ] Run focused suite and require GREEN.

### Task 3: Honest docs and standing regression

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/XP_PLUS_COMPATIBILITY_MATRIX.md`
- Modify: `docs/XP_PLUS_UPGRADE_ROLLBACK.md`

- [ ] Record the rc18.3 built-in `xp upgrade` defect literally.
- [ ] Record supported one-time bootstrap and >=2.1.0 `xp upgrade`.
- [ ] Record report-only stray policy.
- [ ] Re-run schema/handshake no-drift tests.
- [ ] Run complete stable regression, compileall, and `git diff --check`.

### Task 4: Pre-remote B4/B8 gates

- [ ] Reproduce inherited legacy stray defect in a disposable home and inventory it.
- [ ] Print historical V2 probe home and whether it still exists.
- [ ] Build provisional release-shape assets.
- [ ] Run exact user command `python xp-rc183-to-210-bootstrap.py` on an untouched rc18.3 test home.
- [ ] Run A-RB rollback and verify active/previous/candidate metadata.
- [ ] Verify rc18.3 bytes unchanged and real home unchanged.

### Task 5: Create taggable follow-up commit

- [ ] Commit bootstrap/tests/audit/docs once all local gates are green.
- [ ] Build final release assets from that exact commit.
- [ ] Verify SHA256 and repeat B4 using final commit assets.
- [ ] The resulting commit becomes the only `v2.1.0` tag target.

### Task 6: GitHub reviewed release sync

- [ ] Push release branch.
- [ ] Merge through normal PR path only.
- [ ] Require merged tree == taggable commit tree.
- [ ] Tag exact taggable commit.
- [ ] Create draft release and upload bootstrap, engine ZIP, and SHA256SUMS.
- [ ] Download exact draft assets and rerun the user-exact bootstrap + rollback gate.
- [ ] Fresh-clone tag and run version/schema/self-test/full regression.
- [ ] Publish stable/latest only after all gates pass.
- [ ] Reconfirm real active XP and wrapper are byte-identical to milestone start.

## V4 remediation gate

Regression-lock the two V3 failures before proceeding:
- bootstrap top-level imports remain Python stdlib only;
- stable lifecycle activation receives the required keyword-only
  `health_check`, delegated to stable `EngineLifecycle.health_check`.



<!-- XP+-10 A-HC HEALTH AUTHORITY RESTORATION -->
## XP+-10 A-HC — lifecycle health authority restoration

Recorded: `2026-09-13T06:55:10.146737+00:00`.

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
