# CP-08A — Zero-Cost Independence E2E

Status: PASS

Checkpoint base:

- branch: planning/xp-next-bootstrap
- base HEAD: 7a319063157636659ed354ff438cc7d3cb924b98
- stable XP 2.1.0 source: untouched

## Goal

Prove one complete XP Next fixture workflow without a mandatory ChatGPT runtime,
paid API, 9Router, cloud AI, production system, or external network dependency.

The accepted path is:

goal
-> bounded local project context
-> LocalQwenAdapter reasoning
-> bounded read-only plan
-> explicit human sandbox-write approval
-> isolated HermesLocalWorker execution
-> explicit verifier
-> human review
-> explicit Apply/Discard decision
-> CP-07A Apply control
-> post-Apply verification
-> canonical COMPLETED state

## What changed

CP-08A adds ZeroCostE2EService, which composes the existing XP Next controls
instead of bypassing them.

The service requires:

- local Qwen readiness;
- Hermes worker readiness;
- no reported external network use by the reasoning adapter;
- at least one explicit verifier;
- explicit human approval before sandbox mutation;
- a PASS review bundle before Apply;
- an exact reviewed change fingerprint in the final human decision;
- CP-07A recovery creation and post-Apply verification.

No automatic Apply is allowed.

The existing SQLite state store now exposes bounded persistence methods for:

- approvals;
- observable activity trail entries;
- recovery points.

Activity records contain observable actions/status/source/processor only. They do
not store hidden reasoning or chain-of-thought.

## Fixture acceptance boundary

The E2E regression is intentionally fixture-only.

It uses the real LocalQwenAdapter, HermesLocalWorker, isolated workspace,
sandbox review/verifier, CP-07A Apply/recovery/rollback control, and SQLite
job/approval/activity/recovery tables.

At the environment boundary, the test supplies a deterministic local HTTP
server on 127.0.0.1 for health/props/chat-completions and a tiny local
executable standing in for the Hermes CLI process. The executable modifies only
the isolated fixture worktree.

This proves the XP Next orchestration and zero-cost independence contract. It
does not claim that a full Qwen model or full Hermes distribution is currently
installed and operational on this PC.

A previous attempt to download/install the full Hermes distribution on this PC
timed out because the source transfer was extremely slow. That operational
installation is therefore not treated as evidence for this checkpoint.

## Acceptance evidence

Targeted CP-08A/state tests:

- 15 tests PASS.

Full XP Next regression:

- 94 tests PASS.
- zero failures.
- git diff --check PASS.

The E2E fixture proves:

- LocalQwenAdapter completes through loopback transport;
- the bounded planner reaches READY;
- isolated worker mutation is observed;
- verifier/review reaches PASS;
- human review fingerprint matches the exact reviewed sandbox change;
- Apply creates a recovery point;
- post-Apply verification passes;
- original Git HEAD is unchanged;
- only the approved worktree change appears in the original;
- no Git remote is introduced into the sandbox fixture;
- final canonical job state is COMPLETED;
- approvals, activity trail, and recovery point are persisted in SQLite;
- all recorded activity entries are non-live/local for the fixture.

## Failure evidence retained

During CP-08A development:

1. The first E2E targeted run failed only because the test expected approval
   rows in the opposite order from the actual chronological flow. The
   expectation was corrected to sandbox approval followed by Apply approval.
2. The first full regression then found two phase-string expectations still
   pinned to CP-07A. Those tests were updated to CP-08A.
3. The final full regression passed 94/94.

No failed run was accepted as success.

## Safety boundaries

CP-08A does not:

- modify Segeran Jiwa Next or Legacy;
- deploy anything;
- migrate a production database;
- push from a sandbox;
- require a paid API;
- use 9Router;
- silently switch AI/provider;
- expose hidden chain-of-thought;
- weaken CP-07A freshness, recovery, rollback, or post-Apply guards.

## Remaining operational item

Actual PC-local Qwen + llama-server + full Hermes runtime acceptance remains a
separate operational step. The current WSL memory allocation is small enough
that the runtime must be selected and tested deliberately rather than being
declared ready from fixture evidence.

CP-08A closes only the orchestration/independence checkpoint.
