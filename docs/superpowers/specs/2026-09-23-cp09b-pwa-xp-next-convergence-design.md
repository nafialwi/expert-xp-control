# CP-09B — PWA ↔ XP Next Convergence Design

Date: 2026-09-23  
Branch: `planning/xp-next-bootstrap`  
Baseline checkpoint: CP-09A  
Baseline SHA: `cd4808ecc608c710a1bbdf2bbb1a465dc7656bcd`

## 1. Intent

The goal is to converge the existing Expert XP PWA with the governed XP Next engine so the visual application becomes the normal daily interface while preserving all safety guarantees already validated through CP-08J.

The PWA is not allowed to become a second execution engine. It is a human-facing client over governed XP Next services.

Success means a user can:
- open Expert XP visually;
- choose or continue a project;
- describe a task in normal language;
- review the recommended worker;
- explicitly approve worker and sandbox execution;
- observe execution and verification;
- inspect a reviewed result;
- explicitly Apply or Discard;
- see observable activity and recovery status without reading terminal output.

The engineering CLI remains available for diagnostics, recovery, and expert use.

## 2. Current baseline

CP-09A proved that the canonical repository already contains a real local PWA shell with status and Activity Trail surfaces, but not a complete work interface.

The current canonical visual surface is:
- `scripts/xp_visual.py`
- `web/xp_visual/index.html`
- `web/xp_visual/app.js`
- `web/xp_visual/styles.css`
- `web/xp_visual/manifest.webmanifest`
- `web/xp_visual/sw.js`

XP Next already provides the governed workflow primitives:
- project selection and inspection;
- bounded work preparation;
- worker selection and human confirmation;
- isolated workspace execution;
- verification and review;
- Apply/Discard with source guards;
- recovery references;
- persistent job/activity state.

The main architectural gap is that the current CP-08J execution path is synchronous. The review decision is supplied inside one `ZeroCostE2EService.run()` call. A PWA needs the workflow to pause safely at human decision boundaries and resume later.

## 3. Chosen approach

Use a resumable `WorkSessionService` plus a loopback-only Visual Gateway.

Rejected alternatives:

1. Wrapping the CLI from the PWA is rejected because UI behavior would depend on terminal text parsing and process lifetime.
2. Calling the current monolithic `ZeroCostE2EService.run()` directly is rejected because the PWA cannot pause cleanly at approval and review boundaries.
3. A resumable service is selected because it reuses the existing safety controls while exposing explicit state transitions to the UI.

No second mutation path will be introduced.

## 4. Target architecture

```text
Expert XP PWA
    |
    | JSON over loopback HTTP
    v
XP Visual Gateway
    |
    | typed service calls only
    v
WorkSessionService
    |
    +--> ProjectService
    +--> WorkPreparation
    +--> WorkerSelection / confirmation
    +--> IsolatedWorkspace
    +--> Verification / ReviewBundle
    +--> ApplyControl / Discard
    +--> StateStore / Activity / Recovery
```

The Visual Gateway does not execute Git mutations itself.

## 5. Work session contract

A work session is the persistent UI-facing representation of one governed XP Next job.

Required fields:
- session/job id;
- project id and project name;
- source HEAD captured at preparation time;
- user goal;
- current job state;
- recommended worker and resource snapshot;
- worker decision;
- sandbox decision;
- sandbox root when created;
- verification status;
- review summary;
- change fingerprint;
- changed-file summary;
- Apply/Discard decision;
- final state;
- recovery reference when applicable;
- observable activity entries.

No secrets, raw prompts, hidden reasoning, API keys, credentials, or unrestricted environment data are exposed to the PWA.

## 6. State model

The UI consumes the existing XP Next job states and presents human-readable labels:

- `DRAFT` → Belum dimulai
- `PLANNING` → Menyiapkan pekerjaan
- `READY` → Siap dilanjutkan
- `AWAITING_APPROVAL` → Menunggu persetujuan Anda
- `RUNNING` → Sedang bekerja
- `VERIFYING` → Memeriksa hasil
- `READY_TO_REVIEW` → Hasil siap diperiksa
- `APPLYING` → Menerapkan hasil
- `VERIFYING_APPLIED` → Memeriksa hasil terapan
- `COMPLETED` → Selesai
- `NEEDS_ATTENTION` → Perlu perhatian
- `ROLLED_BACK` → Dikembalikan ke kondisi aman
- `CANCELLED` → Dibatalkan

The PWA must derive allowed actions from state. It must not invent or force invalid state transitions.

## 7. User flow

```text
Home
 -> choose/continue project
 -> enter goal
 -> create work session
 -> prepare and inspect project
 -> show worker recommendation
 -> human confirms/declines worker
 -> human approves/declines sandbox
 -> execute in isolated workspace
 -> verification
 -> READY_TO_REVIEW
 -> show diff/review summary
 -> human chooses Apply or Discard
 -> governed ApplyControl/Discard
 -> post-apply verification
 -> final result + Activity Trail + recovery
```

If the user declines worker or sandbox, the source project remains unchanged.

If verification fails, the session enters `NEEDS_ATTENTION`; Apply is unavailable.

If the reviewed change fingerprint changes or no longer matches, Apply is blocked.

## 8. Local gateway API

Versioned endpoints:

```text
GET  /api/v2/snapshot
GET  /api/v2/projects
POST /api/v2/projects/select

POST /api/v2/work-sessions
GET  /api/v2/work-sessions/{id}

POST /api/v2/work-sessions/{id}/worker-decision
POST /api/v2/work-sessions/{id}/sandbox-decision
POST /api/v2/work-sessions/{id}/execute
POST /api/v2/work-sessions/{id}/review-decision
```

The first implementation may expose fewer read-only convenience fields, but these state-changing decisions remain explicit endpoints.

Every mutation endpoint validates:
- loopback request origin/host expectations;
- session existence;
- expected current state;
- project/source identity;
- required human decision;
- allowed action for the current state.

The API returns structured JSON, never terminal-formatted text.

## 9. Review contract

When execution and sandbox verification succeed, the session pauses at `READY_TO_REVIEW`.

The review response must include:
- review status;
- changed-file count;
- changed-file names and bounded human summaries;
- verification result;
- source-project unchanged indicator;
- change fingerprint;
- allowed actions: `APPLY` and/or `DISCARD`.

The PWA may render a bounded diff preview. Raw unrestricted filesystem browsing is out of scope for CP-09B.

Apply requires the exact fingerprint that was reviewed.

Discard must leave the original project unchanged.

## 10. Safety invariants

These are non-negotiable:

1. PWA remains loopback-only during CP-09B.
2. Do not bind the visual gateway to `0.0.0.0`.
3. No production deploy, database migration, branch merge, or release action is added.
4. PWA never copies or edits project files directly.
5. PWA never invokes Git mutation directly.
6. Human confirmation is required for worker selection when the engine requires it.
7. Sandbox approval is explicit.
8. Apply/Discard is explicit and only available after successful review.
9. Apply uses existing source-head and fingerprint guards.
10. No silent worker or AI fallback.
11. Credentials, tokens, hidden reasoning, raw secrets, and private metadata are never serialized to the UI.
12. Segeran Jiwa production is not used for CP-09B development tests.

## 11. Visual information architecture

Primary navigation:
- Home
- Work
- Projects
- Activity
- Settings

### Home

Home prioritizes:
- active project;
- checkpoint and safety status;
- one primary input: “Apa yang ingin Anda kerjakan?”;
- recent important activity;
- clear next step.

Technical SHA, raw paths, and raw logs stay under technical detail views.

### Work

Work is the primary execution surface.

It shows:
- task title and active project;
- human-readable progress timeline;
- worker recommendation and reason;
- worker approval state;
- sandbox approval state;
- verification state;
- review summary;
- bounded file-change preview;
- explicit “Buang Hasil” and “Terapkan” actions;
- Activity Trail for the current job.

The screen must make it obvious whether the original source project has changed.

### Projects

Projects shows:
- registered projects;
- branch;
- status;
- latest checkpoint;
- verifier readiness;
- active-project marker;
- Select, Audit, Inspect, and Continue actions.

### Activity

Activity shows observable actions, sources, processors, and outcomes only. Hidden reasoning is never shown.

### Settings

Settings groups:
- General;
- AI & Worker;
- Recovery;
- System;
- Advanced.

Safety-critical controls such as human approval, sandbox requirement, and silent-fallback prohibition are policy indicators and must not be casually disabled from the UI.

## 12. Access model

During development, the visual service remains available at loopback, currently targeting:

`http://127.0.0.1:8765`

The eventual daily-access target is:

```text
xp
 -> ensure local visual service is running
 -> open Expert XP PWA
```

That launcher cutover is not part of CP-09B.

Cross-device and remote access is also not part of CP-09B. It must use a later authenticated transport and must not be implemented by exposing the loopback server directly to a LAN or the public internet.

## 13. Error handling

All failures become explicit machine-readable states and human-readable messages.

Examples:
- dirty project → `NEEDS_ATTENTION`, source unchanged;
- verifier unavailable → preparation blocked;
- worker unavailable → no silent fallback;
- worker declined → `CANCELLED`;
- sandbox declined → `CANCELLED`;
- verification failure → `NEEDS_ATTENTION`, Apply unavailable;
- fingerprint mismatch → Apply blocked;
- source HEAD drift → Apply blocked;
- post-Apply verification failure → recovery/rollback semantics remain governed by ApplyControl.

HTTP 4xx is used for invalid user/state requests. Internal failures produce bounded 5xx responses without leaking secrets or stack traces to the UI.

## 14. Persistence and resume

A visual work session must be recoverable after browser refresh.

The durable source of truth remains XP Next state, not JavaScript memory.

The PWA may cache shell assets through the service worker, but it must fetch current work-session state from the local gateway.

Refreshing or reopening the browser must never repeat a mutating action automatically.

POST actions must be designed to reject stale or duplicate transitions safely.

## 15. Testing strategy

Implementation is TDD-first.

Required test layers:

1. Unit tests for work-session transitions and allowed actions.
2. Contract tests for JSON serialization and secret exclusion.
3. Gateway tests for state validation and loopback-only behavior.
4. Fixture Git project E2E:
   - create session;
   - confirm worker;
   - approve sandbox;
   - execute;
   - reach `READY_TO_REVIEW`;
   - verify original source unchanged;
   - Discard path;
   - Apply path;
   - post-Apply verification.
5. Negative-path tests:
   - dirty source;
   - verifier missing;
   - declined approval;
   - failed verification;
   - fingerprint mismatch;
   - source-head drift;
   - duplicate/stale transition.
6. Existing XP Next regression must remain green.
7. Existing AF-10 visual/PWA tests must remain green.

Segeran Jiwa production is excluded from these implementation tests.

## 16. Initial implementation boundaries

CP-09B implements the contract and safe backend/gateway foundation only.

It does not yet require the final visual redesign shown in the concept images. That richer UI is the following convergence/UX checkpoint after the gateway contract is proven.

Expected source areas for CP-09B:
- new focused XP Next work-session module(s);
- new/extended local visual gateway module(s);
- dedicated CP-09B tests;
- minimal PWA wiring only if needed to prove the API contract.

Avoid broad refactors of unrelated XP or XP+ code.

## 17. Acceptance criteria

CP-09B is accepted only when:
- the work-session contract exists and is resumable;
- the gateway never bypasses XP Next safety controls;
- review can pause at `READY_TO_REVIEW`;
- Apply/Discard can resume from an existing reviewed session;
- original source remains unchanged before Apply;
- fingerprint/source-head guards are preserved;
- all new tests pass;
- XP Next full regression passes;
- AF-10 visual/PWA regression passes;
- `git diff --check` passes;
- worktree is clean after checkpointing;
- no Segeran Jiwa production source, database, or deployment is touched.

## 18. Follow-up

After CP-09B is proven, the next checkpoint may implement the approved visual flow over this contract: Home, Work, Projects, Activity, and Settings.

Launcher cutover, cross-device access, portability, and final release remain later phases.