# XP Next — CP-04B Bounded Read-Only Planner

Status: SAFE CHECKPOINT
Date: 2026-09-20
Parent: b8db7012e1b25b9564b4655941feea1e10426199

## Purpose

Add the first provider-neutral planning layer after local Qwen reasoning, while preserving the CP-04A boundaries:

- zero-cost first;
- read-only;
- local context;
- no Hermes;
- no source mutation;
- no 9Router/cloud fallback;
- no production actions.

## Plan contract

CP-04B adds:

- PlanStatus
- PlanStepKind
- PlanStep
- Plan
- BoundedReadOnlyPlanner
- verify_plan()

The only plan-step kinds allowed in this checkpoint are:

- OBSERVE_PROJECT
- REVIEW_SOURCE_IDENTITY
- ANALYZE_CONTEXT
- EXPLAIN_FINDINGS

There is no write, patch, delete, deploy, push, migration, database-write, or shell-execution step kind.

Every valid CP-04B plan is forced to:

- risk = read;
- mutation_allowed = false;
- network_allowed = false;
- one to four ordered steps;
- contiguous ordinals;
- static allowlisted step kinds.

## Deterministic planning boundary

The local model does not generate executable step kinds.

Local Qwen provides a bounded reasoning result. The planner records a shortened reasoning summary, but executable plan steps are compiled deterministically from the explicit TaskIntent.

Intent mappings:

INSPECT:
1. OBSERVE_PROJECT
2. REVIEW_SOURCE_IDENTITY
3. EXPLAIN_FINDINGS

ANALYZE:
1. OBSERVE_PROJECT
2. ANALYZE_CONTEXT
3. EXPLAIN_FINDINGS

EXPLAIN:
1. REVIEW_SOURCE_IDENTITY
2. ANALYZE_CONTEXT
3. EXPLAIN_FINDINGS

This prevents model text from introducing write/deploy/tool-execution steps.

A dedicated test supplies hostile reasoning text asking XP to write files, delete tests, push main, and deploy production. The text remains only a non-executable reasoning summary. The generated plan still contains only the static read-only step kinds and passes the structural verifier.

## Fail-closed behavior

If local reasoning is unavailable or returns NEEDS_ATTENTION:

- planner status = NEEDS_ATTENTION;
- plan steps = empty;
- verification = false;
- no fallback provider is used;
- no execution is attempted.

The planner also fails closed if the task or context allows mutation/network use.

## One-snapshot context hardening

The initial CP-04B implementation built the project context once for the returned plan and then indirectly built it a second time inside the reasoning service.

That creates a possible time-of-check/time-of-use inconsistency if project state changes between snapshots.

A tests-first hardening cycle demonstrated the issue:

- expected context-build call count = 1;
- actual before fix = 2.

The service was refactored so build_read_only_plan() now:

1. builds ProjectContext once;
2. creates one TaskIntent;
3. sends that exact context snapshot to the local reasoning adapter;
4. compiles the plan from that same snapshot and reasoning result.

After hardening, the single-snapshot test passes.

## Live local-Qwen acceptance

A temporary local llama-server was started on loopback only using Qwen2.5 1.5B Instruct Q4_K_M.

Acceptance flow:

fixture Git project
-> register
-> select
-> build one bounded ProjectContext snapshot
-> local Qwen readiness
-> local Qwen reasoning
-> deterministic BoundedReadOnlyPlanner
-> verify_plan
-> source-integrity check

Observed first CP-04B live acceptance:

- local Qwen readiness = PASS;
- local Qwen reasoning = COMPLETED;
- plan status = READY;
- verifier = PASS;
- generated ANALYZE steps:
  - OBSERVE_PROJECT
  - ANALYZE_CONTEXT
  - EXPLAIN_FINDINGS
- all plan steps mutation_allowed = false;
- all plan steps network_allowed = false;
- project Git HEAD unchanged;
- project Git status unchanged;
- elapsed time = 35 seconds;
- temporary server stopped.

After the single-snapshot refactor, the complete live acceptance was repeated against the new code path:

- POST_REFACTOR_REASONING = PASS;
- POST_REFACTOR_PLAN = PASS;
- PROJECT_UNCHANGED = PASS;
- elapsed time = 35 seconds;
- temporary server stopped.

## TDD evidence

Tests were written first.

Initial RED:
- missing xp_next.planner;
- missing build_read_only_plan;
- runtime phase still CP-04A.

After implementation the suite passed.

A second RED/green cycle was used for the single-context-snapshot invariant:
- RED proved two context builds occurred;
- refactor reduced it to one;
- complete suite passed again.

Final deterministic suite at checkpoint:
- 59 tests;
- all PASS.

Live local-Qwen planner acceptance is separate from the fast deterministic suite.

## Runtime semantics

CP-04B reports:

- phase = CP-04B;
- ai = LOCAL_READ_ONLY_ADAPTER;
- worker = NOT_INTEGRATED.

The planner is not a worker. It does not execute plan steps.

## Safety boundaries retained

CP-04B:
- does not execute Hermes;
- does not mutate project source;
- does not create a write-capable TaskIntent;
- does not expose write/deploy step kinds;
- does not use 9Router;
- does not use cloud/paid AI;
- does not silently switch models/providers;
- does not inspect or modify Segeran Jiwa;
- does not touch production database state;
- does not deploy production;
- leaves XP+ 2.1.0 stable unchanged.

## Known limitations

Not implemented yet:
- plan execution;
- Hermes worker readiness/integration;
- hard sandbox containment;
- write approval;
- recovery-before-write;
- verifier for mutations;
- Review / Apply / Discard;
- automatic local model lifecycle;
- streaming progress/cancellation;
- PWA.

The current local reasoning/planning path still takes roughly 35 seconds for a small fixture task on the development device. UI work must surface progress explicitly.

## Next allowed checkpoint

CP-05A — Governed Hermes Worker Contract + Isolated Fixture Workspace.

Scope should remain narrow:

- reuse/adapt the proven AgentRuntime/Hermes contract rather than redesign Hermes;
- define XP Next worker request/result contracts;
- create a fixture-only isolated workspace, never the registered source tree;
- first acceptance should prove worker readiness and bounded fixture execution;
- original fixture source must remain unchanged;
- no Apply to original project;
- no push/deploy/database actions;
- recovery metadata must be created before any future write-capable flow;
- commit, push, verify remote SHA, then stop.

CP-05A should not yet make XP a production write agent.
