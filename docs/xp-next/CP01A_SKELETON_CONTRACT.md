# XP Next — CP-01A Skeleton Design and Test Contract

Status: SAFE CHECKPOINT
Date: 2026-09-20

## Purpose

Create the first isolated XP Next skeleton without inheriting the legacy XP runtime workflow.

## Namespace and layout

Product name: xp-next.
Python namespace: xp_next.
Source root: next/src/xp_next.
Tests: next/tests.

XP Next source must not import the legacy xp namespace.

CP-01A uses only the Python standard library. No install or network access is required for tests.

## SQLite schema v1

The schema contract contains:

- meta
- projects
- jobs
- job_steps
- approvals
- activities
- recovery_points
- artifacts
- devices
- preferences
- automations

At CP-01A the schema is validated only with in-memory SQLite. Persistent state is intentionally deferred to CP-01B.

Git remains source authority. SQLite is planned as XP operational-state authority. Filesystem remains project and artifact storage.

## Canonical Job state contract

Normal path:

DRAFT -> PLANNING -> READY -> AWAITING_APPROVAL -> RUNNING -> VERIFYING -> READY_TO_REVIEW -> APPLYING -> VERIFYING_APPLIED -> COMPLETED

Controlled exception states:

- NEEDS_ATTENTION
- ROLLED_BACK
- CANCELLED

Terminal states cannot transition back to RUNNING.

Review occurs before Apply. Applied changes require verification again before COMPLETED.

## Minimal CLI/service contract

Developer CLI:

- xp-next version
- xp-next status
- xp-next doctor

Status must be honest at this checkpoint:

- runtime = SKELETON_ONLY
- AI = NOT_INTEGRATED
- worker = NOT_INTEGRATED
- persistent database = not initialized

Doctor checks only local Python, SQLite and Git availability and performs no network probe.

The pure service functions are designed so a future loopback API can reuse them. CP-01A does not create an HTTP server.

## Zero-cost independence fixture

The future acceptance fixture requires:

- ChatGPT unavailable
- paid API unavailable
- 9Router unavailable
- internet not required
- local Qwen available
- Hermes available

Future required flow:

resolve project -> inspect context -> bounded plan -> write approval -> sandbox execution -> verifier -> review -> apply/discard.

This checkpoint defines the contract only. It does not integrate Qwen or Hermes.

## TDD evidence

Tests were written before XP Next source implementation.

The RED run failed as intended because the xp_next package did not yet exist. Python represented the pre-created source directory as an empty namespace package, so the exact error was ImportError for missing __version__ rather than ModuleNotFoundError. That difference was in the audit script expectation only; no implementation source existed at the time.

The checkpoint resumed from that unchanged RED state instead of deleting or replacing the tests.

## Safety boundary

CP-01A does not:

- call AI;
- call a worker;
- create persistent operational state;
- mutate a real project;
- touch Segeran Jiwa;
- touch any database service;
- deploy production;
- depend on WAITING_GPT, XP_GPT artifacts, package handoff, or mandatory cloud services.

## Next allowed checkpoint

CP-01B only:

- strengthen SQLite constraints and transaction tests;
- add a small SQLite state-store abstraction;
- test restart persistence using a temporary local database;
- confirm source remains independent of legacy xp;
- keep AI, Hermes, PWA and connectors out;
- commit, push, verify remote SHA, then stop.
