# CP-09C Visual UX Convergence Implementation Plan

**Goal:** Connect the canonical Expert XP PWA to the CP-09B visual gateway and provide the approved Home, Work, Projects, Activity, Settings UX.

**Baseline:** CP-09B `db7395bd8efa41efbcc5baca2ec16b112a8bebd1`.

**Implementation method:** Native TDD in isolated worktree `.worktrees/cp09c-visual`.

### Task 1 — Gateway serves canonical PWA + activity API
Files:
- modify `next/src/xp_next/cli.py`
- modify `next/src/xp_next/visual_gateway.py`
- create `next/tests/test_cp09c_visual_ui.py`

RED tests:
- visual-gateway defaults static_root to canonical `web/xp_visual`;
- root HTML from gateway contains the five primary nav destinations;
- `GET /api/v2/activity?limit=...` delegates to bounded public_activity;
- invalid activity limit returns 400.

GREEN:
- add repo-static-root helper;
- add activity GET route with query parsing/clamp delegated to service.

Verify:
- CP09C tests;
- CP09B gateway tests;
- full XP Next regression.

Commit.

### Task 2 — Replace status-only shell with final navigation + visual system
Files:
- rewrite `web/xp_visual/index.html`
- rewrite `web/xp_visual/styles.css`
- update `web/xp_visual/manifest.webmanifest`
- extend `next/tests/test_cp09c_visual_ui.py`

RED static-contract tests:
- Home/Work/Projects/Activity/Settings sections and navigation;
- composer, project list, work timeline, review panel, settings panels;
- accessible labels and status region.

GREEN:
- implement responsive semantic HTML;
- implement approved visual hierarchy and clean professional styling.

Verify HTML/static contracts and AF-10 self-test.

Commit.

### Task 3 — Wire PWA read models
Files:
- rewrite `web/xp_visual/app.js`
- extend `next/tests/test_cp09c_visual_ui.py`

RED tests:
- no legacy `/api/status`;
- app references snapshot/projects/activity/session API v2;
- no verifier command in browser payload;
- safe job-id generation marker;
- credentials same-origin.

GREEN:
- API helper;
- load snapshot/projects/activity;
- render Home/Projects/Activity/Settings;
- local navigation;
- attention banner/error handling.

Run `node --check web/xp_visual/app.js`.

Commit.

### Task 4 — Wire governed Work state machine
Files:
- modify `web/xp_visual/app.js`
- modify `web/xp_visual/index.html`
- extend `next/tests/test_cp09c_visual_ui.py`

RED tests pin action endpoints and UI control IDs.

GREEN:
- create work session from composer;
- render worker recommendation + confirm/decline;
- render sandbox approve/decline;
- execute;
- render READY_TO_REVIEW file/diff summary;
- Apply/Discard with exact fingerprint/revision;
- 409 reload behavior;
- refresh snapshot/activity after every mutation.

No automatic retry of mutations.

Commit.

### Task 5 — PWA cache + final acceptance
Files:
- update `web/xp_visual/sw.js`
- update report `docs/xp-next/CP09C_VISUAL_UX_CONVERGENCE.md`

RED:
- service worker test requires any `/api/` path to bypass cache.

GREEN:
- new cache version;
- shell asset cache;
- API network-only.

Final verification:
- CP09C dedicated tests;
- CP09B dedicated 47;
- full XP Next fresh count;
- AF-10 4/4;
- `scripts/xp_visual.py --self-test`;
- `node --check`;
- `py_compile`;
- `git diff --check`.

Checkpoint report records exact fresh counts and confirms production untouched.
