# CP-09A — PWA Discovery Audit

Date: 2026-09-23
Branch: `planning/xp-next-bootstrap`
Baseline HEAD: `781176b9c4a2efabff636a71ce37309b4431a6f2`

## Purpose

Audit the actual Expert XP visual/PWA assets that exist in the canonical repository after CP-08J, separate historical richer visual work from what is actually present now, and define the convergence target between PWA and XP Next.

## Verified baseline

Fresh verification on NAFI-ALWI-PC:
- XP Next regression: 142/142 PASS.
- AF-10 visual unit tests: 4/4 PASS.
- Visual HTTP self-test: PASS.
- Status API smoke: PASS.
- PWA manifest smoke: PASS.
- Service worker smoke: PASS.
- `git diff --check`: PASS.
- Worktree was clean before this report.

## What actually exists in the canonical branch

Current canonical visual source is:
- `scripts/xp_visual.py`
- `web/xp_visual/index.html`
- `web/xp_visual/app.js`
- `web/xp_visual/styles.css`
- `web/xp_visual/manifest.webmanifest`
- `web/xp_visual/sw.js`

This is a real local PWA shell, not a mockup. It serves a local HTTP UI, exposes `/api/status`, has a standalone manifest, and registers a service worker.

## Current capability audit

### Proven present
- Local-only PWA server.
- Overview/status page.
- Activity Trail projection.
- Project/checkpoint/status display.
- Provider/model/cost/worker/recovery/approval/verification/rollback status fields.
- Installable PWA metadata through `manifest.webmanifest`.
- Service-worker shell cache.
- Mobile responsive CSS.
- Local-only status refresh.
- Hidden-reasoning exclusion is covered by AF-10 tests.

### Not present in the canonical PWA today
- No project picker UI.
- No project switch action.
- No work/chat composer for starting a job.
- No worker recommendation/confirmation UI.
- No sandbox approval UI.
- No execution progress UI.
- No review screen.
- No Apply/Discard action.
- No dedicated Settings screen.
- No full Recovery control screen.
- No direct integration with XP Next `work_flow.py`.

The current canonical PWA is therefore a status/observability surface, not yet the complete daily-use workstation.

## Historical visual evidence

A richer XP+ 2.1.1 visual candidate existed previously with Home, Projects, Activity, Recovery, System, project switching, Offline/Analysis/Live/Worker modes, and an XP Console. That prior candidate must be treated as reusable design/reference, not as the current canonical implementation.

The historical Live/9Router path also had a proven Authorization-header defect. Its code must not be copied blindly.

## Architecture status

The desired final architecture is now clear, but convergence is NOT implemented yet.

```text
Expert XP PWA
    |
    | local authenticated/session API
    v
XP Visual Gateway
    |
    | calls governed XP Next services only
    v
XP Next Engine
    |- ProjectService
    |- WorkFlow
    |- WorkerSelection
    |- Human confirmation
    |- IsolatedWorkspace
    |- Verification
    |- Review
    |- Apply/Discard
    |- State/Recovery
    |
    +--> Local Qwen / governed worker
    |
    +--> Git project
```

Non-negotiable rule: the PWA must never bypass XP Next safety gates. UI buttons such as Apply or Discard must call the same governed engine paths already tested in CP-08H through CP-08J.

## Intended user flow

```text
Open XP
 -> Home
 -> choose project or continue last project
 -> describe work in normal language
 -> XP prepares plan/context
 -> worker recommendation shown
 -> human confirms
 -> sandbox execution
 -> verification
 -> review result/diff
 -> Apply or Discard
 -> Activity Trail records observable actions/outcomes
```

A normal user should not need to know internal CLI flags.

## Access model

### Current proven access
Development/manual:
```bash
PYTHONPATH="$PWD/src" python3 scripts/xp_visual.py --host 127.0.0.1 --port 8765
```
Then open:
`http://127.0.0.1:8765`

Current canonical branch does not prove that a user-facing `xp visual` or default `xp` launcher is installed on this PC. That must be restored/implemented later as a dedicated cutover step.

### Target daily access
Normal user:
```text
xp
 -> starts local visual service if needed
 -> opens the PWA
```

Engineering/recovery CLI remains available separately.

Remote-device access must not expose the PWA by simply binding to `0.0.0.0`. Cross-device access belongs to a later authenticated portability/remote-access phase.

## UX target

Primary navigation should be simple:
1. Home
2. Work
3. Projects
4. Activity
5. Settings

System and Recovery should live under Settings/Advanced unless attention is required.

Home should emphasize:
- active project;
- current checkpoint/status;
- one large "Apa yang ingin dikerjakan?" input;
- last important activity;
- clear safety/attention status.

Work should show a human-readable stage timeline:
- understand project;
- prepare plan;
- worker;
- sandbox;
- verify;
- review;
- Apply/Discard.

Technical paths, SHA values, commands, provider details, and raw logs should be available under "Detail teknis", not dominate the normal screen.

## Gap assessment

PWA existence: VERIFIED.
PWA installability shell: VERIFIED.
PWA status/observability: VERIFIED.
PWA-to-XP-Next work convergence: NOT IMPLEMENTED.
Daily-use UX: NOT IMPLEMENTED.
Settings: NOT IMPLEMENTED.
Final launcher/cutover: NOT IMPLEMENTED.
Remote/mobile cross-device access: NOT IMPLEMENTED.

## Next checkpoint

CP-09B should define and test the local gateway/API contract that exposes XP Next services to the PWA without bypassing safety gates. Implementation should be TDD-first and should initially target a safe fixture project, not Segeran Jiwa production.

CP-09A changes documentation only. No XP engine source, Segeran Jiwa source, production database, or deployment is modified.
