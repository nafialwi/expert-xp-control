# XP+-07 Universal Acceptance Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove XP+ against the FINAL LOCK seven-row universal acceptance matrix and make the same harness reusable as an XP+-09 promotion gate.

**Architecture:** Fixture acceptance tests cover Plain Git, Node, Python, Node+PostgreSQL, and Firebase/static without production dependencies. A separate `scripts/compat-smoke.py` runs Legacy and Next only on temporary local clones/copies, replaces all Git remotes with local temporary remotes, strips production credentials, and hard-fails on source mutation or any guarded DB/deploy call. Runtime backfill re-proves XP+-03, XP+-03.5, and XP+-04 gates.

**Tech Stack:** Python unittest, Git local/bare remotes, Node/npm, existing XP adapters/autopilot/checkpoint/package APIs.

**Spec:** `XP_PLUS_BLUEPRINT_v1.0_FINAL_LOCK.md` §§14–16 and `XP_PLUS_v1_IMPLEMENTATION_PLAN.md` Tasks 11–12.

## Global Constraints

- `work/xp-plus-v1` only; no engine work on protected main/master.
- Legacy/Next smoke uses local clones/copies only.
- Zero production DB mutation and zero production deploy calls.
- Firebase/static must prove PostgreSQL is not assumed without DB mocks.
- Node+PostgreSQL may use the Task-11-sanctioned DB adapter test/mock boundary.
- Any Legacy/Next source mutation is a hard stop.
- XP+-03/03.5/04 consolidated backfill is mandatory before XP+-08.
- Active installed XP remains unchanged.

---

### Task 1: Universal fixture matrix

**Files:**
- Create: `tests/fixtures/plain-git/`
- Create: `tests/fixtures/node/`
- Create: `tests/fixtures/python/`
- Create: `tests/fixtures/node-postgres/`
- Create: `tests/fixtures/firebase-static/`
- Create: `tests/test_acceptance_fixtures.py`

**Interfaces:**
- Produces deterministic fixture coverage for rows 1–5 of §14.

- [ ] Write fixture tests first and verify RED because fixtures are absent.
- [ ] Add Plain Git fixture covering registry, package, protected-branch guard, local safepoint, QA, checkpoint and Final Lock.
- [ ] Add Node runtime + `npm run verify`.
- [ ] Add Python runtime + unittest verification.
- [ ] Add Node+PostgreSQL source verification + DB approval + SQL test with a fake PostgreSQL boundary only.
- [ ] Add Firebase/static onboarding + verification with no PostgreSQL markers and no DB mock.
- [ ] Add synthetic atomic rollback regression.
- [ ] Run `PYTHONPATH=src python -m unittest tests.test_acceptance_fixtures -v`.

### Task 2: Legacy and Next local-copy smoke

**Files:**
- Create: `scripts/compat-smoke.py`
- Create: `tests/test_real_project_contracts.py`
- Modify: `README.md`

**Interfaces:**
- Produces rows 6–7 of §14 and asserts the §15/§16 acceptance sets without production calls.

- [ ] Create a local-only clone/copy helper and replace every source remote with a temporary local bare remote.
- [ ] Create isolated local control repos for lease/safepoint tests.
- [ ] Strip production DB/cloud credentials and guard PostgreSQL apply/test entry points.
- [ ] Legacy: assert profile v1, `PROFILE_INCOMPLETE`, corrective recommendation, Firebase remains a project concern, protected-branch rejection, empty WORK execution on `work/*`, checkpoint/recovery evidence and rollback evidence.
- [ ] Next: assert profile v1, PostgreSQL adapter, actual `npm run verify`, branch guards, existing checkpoint/LOCKED_REMOTE history, new empty WORK package, local safepoint, Human QA, Final Lock, local lease release, source archive/hashes; DB-approval evidence comes from the Node+PostgreSQL fixture.
- [ ] Snapshot originals before/after and hard-stop on mutation.
- [ ] Run targeted real-project smoke with explicit local paths.

### Task 3: Mandatory XP+-03 / 03.5 / 04 backfill

**Files:**
- Reuse: `scripts/compat-smoke.py`

**Interfaces:**
- Produces consolidated promotion evidence.

- [ ] Re-run Doctor: Legacy=`PROFILE_INCOMPLETE`, Next=`WORK_READY`.
- [ ] Re-run cwd resolver on both projects and prove registry `last_active` bytes unchanged.
- [ ] Build deep first then compact bundles for both projects into a temp directory.
- [ ] Assert both compact/deep ratios `< 0.35` and project source unchanged.

### Task 4: Promotion evidence and regression

**Files:**
- Modify: `README.md`

- [ ] Run all XP+-07 targeted tests.
- [ ] Run full unittest discovery.
- [ ] Run compileall and `git diff --check`.
- [ ] Run isolated `xp self-test`.
- [ ] Print the complete seven-row acceptance matrix, read-only proof, no-production-call proof and backfill evidence.
- [ ] Commit `test(xp+): add universal acceptance and real-project smoke`.
- [ ] Push only after all gates pass.


---

## A+ Architecture Ruling — Binding V4 Amendment

### Zone 1 — Original Legacy/Next repositories

- [ ] Hash the complete tree including `.git`, ignored paths, runtime/cache paths,
      regular files and symlink targets before all acceptance activity.
- [ ] Execute no Git/project/interpreter command with cwd inside either original.
- [ ] Make a physical, non-hardlinked temporary copy using plain file reads.
- [ ] Re-hash complete original trees after all acceptance activity.
- [ ] Hard stop unless before/after full-tree SHA evidence is identical.

### Zone 2 — Temporary acceptance copies

- [ ] Protect HEAD for scenarios that expect no source commit.
- [ ] Protect tracked diff bytes.
- [ ] Protect non-ignored untracked set and contents.
- [ ] Protect `.xp/` explicitly even when Git ignores parts of it.
- [ ] Allow only Git-ignored build/cache/runtime artifact changes.
- [ ] For every changed ignored artifact, require `git check-ignore -v` evidence.
- [ ] Add no silent harness exclusions. `harness_added_exclusions=[]`.
- [ ] Report ignored changes informationally; any canonical boundary change is a hard stop.

### Backfill

- [ ] Re-run XP+-03 Doctor and XP+-03.5 cwd behavior only on copies.
- [ ] Re-run XP+-04 deep-first/compact bundle ratio on copies.
- [ ] Preserve the user's real XP registry/control state.
