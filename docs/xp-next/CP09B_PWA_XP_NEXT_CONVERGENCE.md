# CP-09B — PWA ↔ XP Next Convergence Evidence

Date: 2026-09-23

## Scope

CP-09B establishes the safe backend contract between the existing Expert XP visual/PWA surface and XP Next. It does not yet implement the final Home/Work/Projects/Activity/Settings redesign; that is the CP-09C follow-up.

Approved design:
`docs/superpowers/specs/2026-09-23-cp09b-pwa-xp-next-convergence-design.md`

Implementation plan:
`docs/superpowers/plans/2026-09-23-cp09b-pwa-xp-next-convergence.md`

## Git evidence

- Planning design commit: `37c91a40534adf1386efce1f23842f8e6a631327`
- Planning plan commit: `773da273cf7a5a3c16757dc9a9fdb59bb44c8224`
- Isolated implementation worktree base: `3c664f4729383a40dc5be534888d193a4210d2b9`
- Verified implementation HEAD before this evidence report: `4bc80aae3f8e0bc02acde1b8e331c7a62efbb99c`
- Implementation branch: `work/cp09b-pwa-convergence`
- `git diff --check` across implementation range: PASS

The exact final checkpoint SHA is verified externally after the evidence/report commit; a commit cannot truthfully contain its own future SHA.

## Implemented architecture

```text
Expert XP PWA / visual client
        |
        | same-origin JSON over loopback
        v
XP Visual Gateway
        |
        | serialized governed service dispatch
        v
WorkSessionService
        |
        +--> ProjectService / prepare_work
        +--> WorkerSelector + human confirmation
        +--> explicit sandbox approval
        +--> ZeroCostE2EService pause-at-review
        +--> verifier / ReviewBundle
        +--> ApplyControl / Discard
        +--> StateStore / Activity / Recovery
```

The browser is not a second execution engine. It never performs Git mutation, file copy, Apply, Discard, verification, or recovery directly.

## Durable session contract

XP Next local-state schema is now version 2 and adds a `work_sessions` table with:
- one session per XP Next job;
- bounded JSON payload;
- optimistic integer revision;
- v1→v2 in-place local-state migration;
- stale revision rejection.

A browser refresh or gateway restart can reload the durable session from XP Next state rather than JavaScript memory.

## Governed phase boundary

The original zero-cost E2E path now exposes an internal phase boundary:
- execute an already-approved job to `READY_TO_REVIEW`;
- stop with the original source unchanged;
- reconstruct and freshly verify the sandbox on resume;
- Apply or Discard only through the existing ApplyControl path.

The existing `ZeroCostE2EService.run()` compatibility path remains covered by legacy regression tests.

## Public visual contract

The browser-facing work-session projection is allow-listed. It exposes useful UI state such as:
- project id/name;
- user goal;
- human-readable job state;
- visible worker recommendation/confirmation;
- sandbox approval state;
- review status, changed-file names, bounded diff, fingerprint;
- Apply/Discard state;
- recovery availability;
- observable Activity Trail entries;
- allowed next actions.

It does not expose:
- raw worker prompt;
- verifier argv;
- internal sandbox path;
- tokens/credentials;
- hidden reasoning;
- unrestricted environment data.

Project, snapshot, capability, and activity views are also bounded; Activity Trail responses are capped at 50 items.

## Visual Gateway safety

The CP-09B gateway:
- binds to loopback only;
- rejects `0.0.0.0`;
- creates an opaque local session cookie;
- uses `HttpOnly; SameSite=Strict; Path=/`;
- requires exact same-origin `Origin` for mutations;
- requires valid local session cookie for mutations;
- requires `application/json`;
- does not enable permissive CORS;
- caps request body size;
- maps stale/invalid state to bounded 4xx responses;
- emits generic 500 responses without browser-visible Python traceback.

A real HTTP E2E test exposed SQLite thread affinity with `ThreadingHTTPServer`. The final implementation keeps the threaded gateway but:
- opens the XP Next SQLite connection with `check_same_thread=False`;
- serializes every gateway service dispatch under one `RLock`.

This preserves safe local-state access while avoiding concurrent DB/service mutation from browser requests.

## Development access

CP-09B adds a development-only command:

```text
xp-next visual-gateway --host 127.0.0.1 --port 8765
```

The command constructs the real `WorkSessionService`, local Qwen adapter, worker selector, and loopback gateway.

It intentionally does **not** auto-serve the legacy PWA by default, because the legacy UI has not yet been converged to the v2 work-session API. An explicit `--static-root` may be supplied for development. Final `xp` launcher cutover remains out of scope.

## Fresh verification evidence

### Dedicated CP-09B suite

Command covered:
- session store/migration;
- execution phases;
- WorkSessionService;
- visual gateway;
- HTTP E2E.

Result:

```text
Ran 41 tests
OK
```

### Full XP Next regression

```text
Ran 183 tests
OK
```

### Existing AF-10 visual regression

```text
Ran 4 tests
OK
```

### Existing PWA self-test

```text
AF10_PWA_HTTP_SMOKE=PASS
AF10_STATUS_API=PASS
AF10_MANIFEST=PASS
AF10_SERVICE_WORKER=PASS
```

### Repository hygiene

```text
git diff --check = PASS
```

Only intentional Expert XP CP-09B source/test files were changed.

## HTTP fixture acceptance

All E2E flows use temporary isolated Git fixtures and local loopback reasoning. No Segeran Jiwa path or production service is used.

Proven behaviors:
- Discard flow: PASS — reaches `READY_TO_REVIEW`, original remains clean/SAFE, then `CANCELLED / DISCARDED`.
- Apply flow: PASS — reviewed change becomes `COMPLETED / APPLIED`, post-Apply verification passes, recovery point recorded.
- Restart/resume: PASS — gateway/runtime can reopen at `READY_TO_REVIEW`; Discard resumes without rerunning worker.
- Dirty original: PASS — blocked as HTTP 409 before job execution.
- Worker decline: PASS — `CANCELLED`, worker never runs.
- Sandbox decline: PASS — `CANCELLED`, worker never runs.
- Failed verifier: PASS — `NEEDS_ATTENTION`, Apply unavailable.
- Wrong fingerprint: PASS — `NEEDS_ATTENTION`, original unchanged.
- Source HEAD drift: PASS — Apply blocked, external drift not overwritten.
- Missing sandbox: PASS — `NEEDS_ATTENTION`, original unchanged.
- Stale revision/retried mutation: PASS — HTTP 409, no duplicate approval/side effect.
- Invalid Origin/cookie: PASS — HTTP 403 before service mutation.

## Production boundary

- Segeran Jiwa production source: UNTOUCHED.
- Segeran Jiwa production database: UNTOUCHED.
- Production deployment: NONE.
- Branch merge/release: NONE.
- Remote/mobile exposure: NONE.
- Visual gateway remains loopback-only.

## Follow-up

CP-09C should implement the approved visual UX over this proven contract:
- Home;
- Work;
- Projects;
- Activity;
- Settings;
- review/diff presentation;
- Apply/Discard controls;
- human-friendly progress timeline.

Only after visual convergence/UAT should the project proceed to portability/remote-access validation and final `xp` launcher cutover.
