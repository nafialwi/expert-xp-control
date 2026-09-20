# XP Next — CP-01B SQLite State Store Checkpoint

Status: SAFE CHECKPOINT
Date: 2026-09-20
Parent: cfc8005c03a18d91803a7b86f26f9f0bb2c9854e

## Purpose

Turn the CP-01A SQLite schema contract into a small, restart-persistent local state-store abstraction without adding AI, workers, UI, networking, connectors, or real-project mutation.

## Implemented

xp_next.state_store.StateStore now provides the first bounded state operations:

- register a project;
- read a project;
- select exactly one active project;
- read the active project;
- create a job in DRAFT;
- read a job;
- transition a job only through the canonical JobState graph;
- reopen the same SQLite file and recover project/job state.

The store is path-injected. XP Next does not yet create a canonical persistent database under the user's home directory.

## Schema hardening

SQLite schema v1 now enforces:

- foreign keys enabled;
- one active project maximum through a partial unique index;
- canonical JobState values at the database boundary;
- job risk limited to read, write, or high_risk;
- active/live/enabled booleans constrained to 0/1;
- non-negative job-step ordinal;
- unique project root path;
- explicit schema version.

If a database already reports another schema version, initialization fails closed with SchemaVersionError; XP Next does not overwrite the version marker.

## Transaction behavior

StateStore mutations use SQLite transactions.

Verified behavior:

- switching the active project leaves exactly one active project;
- selecting a missing project does not clear the existing active project;
- duplicate project root insertion fails without leaving a partial second project;
- invalid job transition leaves the current state unchanged;
- a compare-and-update guard detects a concurrent job-state change;
- orphan jobs are rejected by foreign-key enforcement.

Cross-process writer leases and lock expiry are not implemented in CP-01B and remain future work.

## Persistence acceptance

A temporary database was created, populated, closed, reopened, and checked.

Verified after reopen:

- active project identity persisted;
- job identity persisted;
- job risk persisted;
- job state persisted.

A separate local smoke database also passed reopen persistence and was deleted after the test.

No canonical user database was activated.

## TDD evidence

CP-01B tests were written first.

Expected RED result occurred because SchemaVersionError and the new state store did not yet exist and CP-01A status still reported CP-01A.

After minimal implementation and hardening, the complete XP Next suite passes.

## Zero-cost and isolation guarantees retained

CP-01B:

- uses Python standard library SQLite only;
- performs no network probe for state operations;
- imports no legacy xp runtime;
- contains no WAITING_GPT or XP_GPT runtime path;
- does not call Qwen;
- does not call Hermes;
- does not call 9Router;
- does not use Supabase as XP runtime state;
- does not mutate Segeran Jiwa;
- does not deploy or change a production database.

## Known limitations

Not yet implemented:

- canonical XP Next runtime home and database path;
- project discovery and onboarding into this store;
- schema migrations beyond v1;
- cross-process lease and locking policy;
- Activity Trail persistence API;
- approval API;
- recovery-point API;
- artifact API;
- AI or worker integration.

## Next allowed checkpoint

CP-02A — Canonical Local Runtime Home + Project Registry Activation.

Scope remains small:

- define XP Next home paths;
- create and open the canonical local SQLite database safely;
- register, list, and switch local project fixtures through a project service;
- expose state-backed status without AI;
- test fresh start and process restart;
- do not integrate Qwen, Hermes, PWA, connectors, real production projects, or remote services;
- commit, push, verify remote SHA, then stop.
