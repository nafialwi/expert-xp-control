# CP-08F — Worker Recommendation + Confirmation Integration

Status: PASS

Base:
- branch: planning/xp-next-bootstrap
- base HEAD: 8bfba8b21442b0161959462ee56cf1f80dddde44
- CP-08E explicit resource/capability-aware selection: PASS
- stable XP 2.1.0 source: untouched

## Goal

Bind the visible CP-08E worker recommendation to an explicit human
confirmation and then prove that XP executes exactly that confirmed backend.

The worker decision must become part of the job approval and Activity Trail.
A declined, stale, mismatched, or unavailable worker must fail closed without
trying an alternate worker.

## Human confirmation contract

CP-08F adds:

- HumanWorkerConfirmation;
- ConfirmationStatus: CONFIRMED, DECLINED, NEEDS_ATTENTION;
- WorkerConfirmation;
- confirm_worker_selection().

A confirmation is valid only when:

1. a safe backend was visibly offered by the selector;
2. the human-confirmed backend exactly matches that visible backend;
3. the confirmation comes from an explicit human reviewer;
4. the confirmation is approved;
5. the exact backend passes a fresh readiness/resource recheck.

The fresh check converts the recommendation into an explicit exact-backend
selection. It does not search for or substitute another backend.

## Job-flow integration

ZeroCostE2EService can now receive a WorkerSelection together with its
WorkerConfirmation.

When supplied, the job records:

- worker recommendation/activity including the local resource snapshot;
- worker-selection approval;
- human confirmation activity;
- exact runtime backend binding before reasoning/execution.

The runtime worker readiness identity must equal the confirmed backend.
If it differs, the job transitions to NEEDS_ATTENTION before worker execution.

If the human declines the recommendation, the job transitions to CANCELLED
before local reasoning, sandbox mutation, verification, or Apply.

Existing callers that already supply one fixed worker remain supported; CP-08F
does not silently retrofit automatic selection into older flows.

## Activity Trail

A confirmed execution now exposes observable steps such as:

- recommend_worker;
- confirm_worker;
- bind_confirmed_worker;
- isolated_lightweight_local or the explicitly bound worker;
- sandbox_review;
- human_review;
- apply_reviewed_change;
- post_apply_verify.

Only observable decisions, sources, statuses, resources, and outcomes are
stored. Hidden chain-of-thought is not stored.

## Acceptance evidence

Targeted selection/confirmation/E2E/worker suite:
- 35 tests PASS.

Full XP Next regression:
- 126 tests PASS;
- zero test failures;
- git diff --check PASS.

New confirmation coverage proves:

- a visible lightweight recommendation can be human-confirmed;
- confirmation performs a fresh exact-backend readiness/resource check;
- a confirmation for another backend is rejected;
- a declined recommendation never binds a worker;
- resource degradation between recommendation and confirmation blocks the
  confirmation;
- a nonhuman confirmation is rejected;
- E2E execution records recommendation, confirmation, and exact binding before
  worker execution;
- a declined E2E job stops before reasoning or worker execution;
- a runtime worker identity that differs from the confirmed backend is blocked
  with NEEDS_ATTENTION and is never executed.

## No-silent-switch invariant

CP-08F makes the worker decision durable and executable only as an exact
binding:

recommend backend A
-> human confirms backend A
-> fresh check validates backend A
-> runtime identity must still be backend A
-> execute backend A only

Any mismatch stops the job. There is no A-to-B fallback inside this flow.

## Known non-blocking warning

The pre-existing Python 3.14 SQLite ResourceWarning can still appear in parts
of the regression suite. It remains non-failing and is not treated as resolved
by CP-08F.

## Safety boundaries

CP-08F does not:
- automatically approve a worker recommendation;
- silently switch workers or providers;
- convert free-form AI output into lightweight filesystem commands;
- apply sandbox changes without the existing human review/Apply gate;
- deploy;
- migrate production data;
- touch Segeran Jiwa projects;
- require paid API, cloud AI, or 9Router;
- weaken recovery, rollback, or post-Apply verification.

## Remaining work

XP can now recommend, confirm, bind, execute, verify, review, and Apply an exact
worker through the internal job flow. The main remaining product gap is a
human-friendly command/UI surface that presents these decisions without the
caller having to assemble internal objects.

A following bounded checkpoint should expose this flow through the XP command
surface while preserving all current approval and no-fallback guarantees.
