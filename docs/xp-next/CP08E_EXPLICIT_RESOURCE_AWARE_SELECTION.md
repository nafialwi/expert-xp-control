# CP-08E — Explicit Resource/Capability-Aware Worker Selection

Status: PASS

Base:
- branch: planning/xp-next-bootstrap
- base HEAD: 915e71678fe7a9cf0acd2009d750a31f4de73bb1
- CP-08D lightweight local execution: PASS
- stable XP 2.1.0 source: untouched

## Goal

Add a decision-only worker selection layer that can distinguish simple bounded
local edits from higher-capability agentic work while considering real worker
readiness and local PC resources.

The selector must never execute a worker and must never silently switch to a
different worker when an explicitly requested worker is unavailable.

## Selection contract

WorkerSelector supports two distinct outcomes before execution:

- RECOMMENDED: XP can suggest a compatible worker, but explicit confirmation is
  still required before execution.
- SELECTED: the caller explicitly requested that backend and the backend passed
  compatibility, readiness, and resource checks.

If the requested backend fails a check, selection returns NEEDS_ATTENTION and
backend_id remains empty. No alternate backend is attempted.

This makes worker choice visible and auditable rather than an invisible
provider fallback.

## Lightweight compatibility

CP-08E adds a pure shape validator for the CP-08D lightweight JSON operation
contract.

Only explicit create_text or replace_text payloads that satisfy the bounded
schema are considered compatible with lightweight_local.

A prose or agentic prompt is never converted automatically into a filesystem
operation by the selector.

## Resource policy

ResourceSnapshot can be injected for deterministic tests or read locally from
Linux /proc/meminfo plus the logical CPU count.

The initial conservative profiles are:

- lightweight_local: at least 32 MiB available memory and 1 logical CPU;
- hermes: at least 4096 MiB available memory and 4 logical CPUs.

The Hermes threshold is a policy guard informed by CP-08B, where the current
low-memory WSL configuration could expose the 64k runtime but real Hermes tasks
still timed out. The threshold is not presented as a universal Hermes hardware
requirement; it is the current XP Next recommendation policy and can be revised
through a later measured checkpoint.

## No-silent-switch behavior

Examples covered by tests:

- explicit lightweight_local plus incompatible prose -> NEEDS_ATTENTION;
- explicit Hermes plus unavailable readiness -> NEEDS_ATTENTION;
- explicit Hermes plus insufficient memory -> NEEDS_ATTENTION;
- unknown explicit backend -> NEEDS_ATTENTION.

In every explicit-failure case, no fallback backend is selected or executed.

For an unrequested worker decision:

- compatible bounded JSON can be RECOMMENDED as lightweight_local;
- agentic work can be RECOMMENDED as Hermes only if readiness and resource
  policy pass;
- otherwise XP returns NEEDS_ATTENTION.

A recommendation still requires confirmation before execution.

## Real PC resource smoke

The selector was exercised against the actual PC/WSL resource snapshot and the
installed local worker objects.

Observed at the smoke-test moment:

- MemAvailable: 1077 MiB;
- logical CPUs: 4.

Results:

1. bounded replace_text operation
   - status: RECOMMENDED
   - backend: lightweight_local
   - requires confirmation: yes

2. nontrivial agentic prompt
   - status: NEEDS_ATTENTION
   - backend: none
   - Hermes was blocked by the current 4096 MiB recommendation threshold

3. the same bounded operation with explicit lightweight_local request
   - status: SELECTED
   - backend: lightweight_local
   - no alternate backend considered

This is the intended current-hardware behavior.

## Acceptance evidence

Targeted selection/worker regression:
- 27 tests PASS.

Full XP Next regression:
- 118 tests PASS;
- zero test failures;
- git diff --check PASS.

The existing Python 3.14 SQLite ResourceWarning can still appear during some
E2E tests. It remains non-failing and was already known before CP-08E; this
checkpoint does not treat the warning as evidence of a clean resource lifecycle.

## Safety boundaries

CP-08E does not:
- execute a worker from the selector;
- automatically confirm a recommendation;
- silently fall back to another worker;
- translate free-form model output into direct file operations;
- mutate original projects;
- deploy;
- migrate production data;
- touch Segeran Jiwa projects;
- use paid API, cloud AI, or 9Router;
- weaken sandbox, review, Apply, recovery, rollback, or post-Apply checks.

## Remaining work

The selector now produces a safe visible decision, but the human-facing XP flow
still needs to present that decision and bind the confirmed backend into one
integrated job workflow.

The next bounded checkpoint should integrate recommendation/confirmation with
the job/activity flow so XP can show, for example:

- Recommended worker: lightweight_local
- Reason: bounded deterministic edit
- Resource state: sufficient
- Confirm worker? yes/no

and then execute exactly the confirmed backend with no fallback.
