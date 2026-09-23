# CP-09C — Visual UX Convergence

Date: 2026-09-23
Baseline: CP-09B remote-safe `db7395bd8efa41efbcc5baca2ec16b112a8bebd1`
Feature branch: `work/cp09c-visual-ux`

## Outcome

CP-09C converts the canonical Expert XP PWA from the AF-10 status-only surface into a PWA client for the governed XP Next work-session contract.

The browser does not become a second execution engine. Project mutation, worker control, sandbox execution, verification, review, Apply/Discard, state persistence, recovery, and Git guards remain owned by XP Next.

## Visual surface

Primary navigation now contains:

- Home
- Work
- Projects
- Activity
- Settings

### Home

Home provides:
- active project status;
- primary “Apa yang ingin Anda kerjakan?” composer;
- engine/recovery/session status;
- latest work session;
- recent Activity Trail.

### Work

Work renders the governed progression:

```text
prepare
 -> worker recommendation / human decision
 -> sandbox decision
 -> execute
 -> verification
 -> READY_TO_REVIEW
 -> Apply or Discard
```

The visual client sends the current revision with every mutation and the exact review fingerprint with Apply/Discard.

HTTP 409 is treated as stale state: the PWA reloads the latest state and does not retry the mutation automatically.

### Projects

Projects shows bounded project metadata and supports explicit project selection through the CP-09B gateway.

### Activity

Activity consumes the new bounded:

`GET /api/v2/activity?job_id=<optional>&limit=<1..50>`

Only observable action/status/source/processor/result data is rendered. Hidden reasoning and internal metadata remain excluded.

### Settings

CP-09C Settings is intentionally read-only for safety-critical policy. It shows:
- local capability status;
- recovery count;
- loopback gateway origin;
- Human approval required;
- Sandbox required;
- No silent fallback;
- reviewed Apply policy.

## Gateway convergence

`xp-next visual-gateway` now serves the repository canonical `web/xp_visual` directory by default.

Development override `--static-root` remains available.

The visual gateway remains loopback-only.

The old `scripts/xp_visual.py` route remains only as the AF-10 legacy visual/status compatibility and self-test path; the XP Next gateway is the CP-09C work-session path.

## PWA behavior

The service worker caches shell assets only:
- `/`
- `/index.html`
- `/styles.css`
- `/app.js`
- `/manifest.webmanifest`

Every same-origin path beginning with `/api/` is network-only and is never served from the service-worker cache.

Non-GET requests are not cached.

## Safety properties

- Gateway bind remains loopback-only.
- Same-origin cookie/origin mutation guards from CP-09B remain unchanged.
- Browser never sends a raw verifier command.
- Browser never edits project files or invokes Git directly.
- Browser does not retry stale mutation automatically.
- Human worker confirmation remains explicit.
- Sandbox approval remains explicit.
- Apply/Discard remains explicit.
- Apply carries the exact reviewed fingerprint.
- No silent AI/worker fallback is introduced.
- Segeran Jiwa production is excluded from CP-09C tests.

## Fresh verification evidence

### CP-09C dedicated

```text
Ran 19 tests in 1.529s
OK
```

### CP-09B regression

```text
Ran 47 tests in 28.638s
OK
```

### Full XP Next regression

```text
Ran 208 tests in 48.338s
OK
```

### AF-10 legacy visual regression

```text
Ran 4 tests
OK
```

### Legacy PWA self-test

```text
AF10_PWA_HTTP_SMOKE=PASS
AF10_STATUS_API=PASS
AF10_MANIFEST=PASS
AF10_SERVICE_WORKER=PASS
```

### Static/runtime hygiene

```text
node --check web/xp_visual/app.js : PASS
node --check web/xp_visual/sw.js  : PASS
python py_compile gateway/cli     : PASS
git diff --check                  : PASS
```

## Production boundary

- Segeran Jiwa production source: UNTOUCHED.
- Segeran Jiwa production database: UNTOUCHED.
- Production deployment: NONE.
- Public/LAN exposure: NONE.
- Final `xp` launcher cutover: NOT YET.
- Cross-device remote access: NOT YET.

## Access for visual UAT

Current development/UAT entry point:

```bash
xp-next visual-gateway --host 127.0.0.1 --port 8765
```

Then open:

`http://127.0.0.1:8765`

The canonical PWA is now served automatically; `--static-root` is no longer required.

## Recommended next checkpoint

Human Visual UAT should validate:
- first-glance clarity;
- Home composer;
- project selection;
- worker/sandbox decisions;
- execution waiting state;
- review readability;
- Apply/Discard confidence;
- Activity Trail readability;
- Settings clarity;
- desktop and phone-sized responsiveness.

After Visual UAT, address only observed usability defects, then proceed to portability/recovery validation and final `xp` launcher cutover.
