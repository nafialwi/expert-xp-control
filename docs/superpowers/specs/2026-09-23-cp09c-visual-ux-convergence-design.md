# CP-09C — Visual UX Convergence Design

Date: 2026-09-23
Branch: `work/cp09c-visual-ux`
Baseline: CP-09B remote-safe `db7395bd8efa41efbcc5baca2ec16b112a8bebd1`

## Intent

Turn the existing Expert XP PWA from an AF-10 status-only surface into the normal visual client for the governed XP Next CP-09B workflow.

The approved visual direction is: clean, professional, easy to understand, PWA-first, with five primary areas:
- Home
- Work
- Projects
- Activity
- Settings

The browser remains a client. XP Next remains the only execution engine.

## Actual baseline

The canonical `web/xp_visual` shell currently calls legacy `/api/status` and only displays overview/activity snapshot data.

CP-09B now provides a loopback-only gateway with:
- `GET /api/v2/snapshot`
- `GET /api/v2/projects`
- project selection
- resumable work-session creation
- worker decision
- sandbox decision
- execute-to-review
- Apply/Discard review decision

The current `xp-next visual-gateway` only serves static PWA assets when `--static-root` is supplied manually.

## CP-09C target

`xp-next visual-gateway` should serve the canonical `web/xp_visual` PWA by default.

The PWA should:
1. load snapshot + projects + recent activity;
2. show the active project and latest work state;
3. allow project selection;
4. let the user describe work in normal language;
5. render worker recommendation and explicit confirm/decline;
6. render sandbox approval;
7. execute and wait for verified review;
8. show bounded changed-file/diff review;
9. provide explicit Apply / Discard;
10. refresh Activity Trail and Home status after every state-changing action.

## Information architecture

### Home
- one primary “Apa yang ingin Anda kerjakan?” composer;
- active project;
- safety/local status;
- latest session;
- compact system/recovery status;
- recent activity;
- clear next action.

### Work
- goal + active project;
- human-readable progress timeline;
- worker recommendation and reason;
- worker confirmation controls;
- sandbox decision controls;
- execution status;
- review result;
- changed-file list and bounded diff;
- Apply / Discard;
- error/attention state.

### Projects
- project list;
- active marker;
- branch/head/clean status;
- Select action;
- contextual explanation if project is dirty or verifier is unavailable.

### Activity
- bounded observable Activity Trail only;
- no hidden reasoning;
- filter display by status locally in the browser.

### Settings
Read-only operational settings for CP-09C:
- local/loopback access;
- capability status;
- human approval required;
- sandbox required;
- no silent fallback;
- recovery count;
- PWA/service-worker status;
- gateway endpoint.
Safety policy is informative, not casually toggleable.

## Gateway additions

Add read-only:
`GET /api/v2/activity?job_id=<optional>&limit=<1..50>`

Do not add CORS. Host/session/origin mutation protections remain unchanged.

## Static serving

`xp-next visual-gateway` defaults to repository canonical `web/xp_visual` when `--static-root` is omitted.

`--static-root` remains an explicit development override.

The old `scripts/xp_visual.py` AF-10 self-test remains compatible as a legacy status-server test. CP-09C's actual daily visual path is the XP Next gateway.

## Browser mutation contract

All POSTs use:
- same-origin fetch;
- `credentials: "same-origin"`;
- `Content-Type: application/json`;
- current `expected_revision`.

The PWA never sends `verifier_command`.

Job IDs are generated as path-safe `work-<uuid>`.

The UI never repeats a stale mutation automatically. HTTP 409 prompts a fresh reload.

## UX state mapping

- `AWAITING_APPROVAL` + CONFIRM_WORKER → “Pilih worker”
- `AWAITING_APPROVAL` + APPROVE_SANDBOX → “Izinkan sandbox”
- `AWAITING_APPROVAL` + EXECUTE → “Siap dijalankan”
- `RUNNING` → “Sedang bekerja”
- `VERIFYING` → “Memeriksa hasil”
- `READY_TO_REVIEW` → “Hasil siap diperiksa”
- `APPLYING` → “Menerapkan hasil”
- `COMPLETED` → “Selesai”
- `NEEDS_ATTENTION` → “Perlu perhatian”
- `CANCELLED` → “Dibatalkan”

## Visual design

Default light neutral surface with restrained teal/green accent, readable typography, rounded cards, clear hierarchy, and minimal technical noise.

Technical SHA/path/raw detail is secondary and hidden behind compact detail blocks.

Responsive behavior:
- desktop: fixed sidebar + content;
- tablet/mobile: compact top navigation/stacked cards;
- all actions remain usable without horizontal scrolling.

## PWA/offline behavior

Service worker caches shell assets only.

All `/api/` requests are network-only and never served stale from cache.

On API failure the UI clearly says local XP service is unavailable; it must not pretend success.

## Safety

- loopback-only gateway remains mandatory;
- no production deploy or database action;
- no direct Git or filesystem mutation from JS;
- no raw verifier command from browser;
- no silent worker/AI switching;
- Apply/Discard only from CP-09B service state;
- credentials/hidden reasoning never rendered;
- Segeran Jiwa production excluded from CP-09C tests.

## Acceptance

CP-09C is complete when:
- gateway serves canonical PWA by default;
- Home/Work/Projects/Activity/Settings exist;
- PWA uses only `/api/v2` for XP Next state/actions;
- activity endpoint is bounded and secret-safe;
- project select works;
- work-session worker/sandbox/execute/review controls are wired;
- service worker bypasses every `/api/` request;
- static JS syntax passes;
- CP-09B 47-test suite remains green;
- full XP Next regression remains green;
- AF-10 4-test legacy visual regression remains green;
- PWA self-test remains green;
- worktree is clean at checkpoint;
- no Segeran Jiwa production, production DB, or deploy is touched.
