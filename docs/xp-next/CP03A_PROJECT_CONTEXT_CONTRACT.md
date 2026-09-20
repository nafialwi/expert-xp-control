# XP Next — CP-03A Project Context + Read-Only Task Contract

Status: SAFE CHECKPOINT
Date: 2026-09-20
Parent: 2f26857974c67c33c6e58128cac8eab33fc4fbc5

## Purpose

Compose the local project identity, bounded inspection facts, local capabilities, source identity, and user request into a deterministic read-only ProjectContext before any AI reasoning or worker execution is allowed.

## Read-only TaskIntent

The first task contract intentionally supports only:

- INSPECT
- ANALYZE
- EXPLAIN

Every CP-03A TaskIntent is forced to:

- risk = read
- mutation_allowed = false
- network_allowed = false
- source = user

An empty goal is rejected.

No write/fix/build/deploy intent exists in this checkpoint.

## ProjectContext

ProjectContext separates data into explicit categories:

### Project identity

Persistent registered facts:

- id
- name
- root path
- source kind

### Observed facts

Facts directly observed from bounded local inspection:

- project root
- known top-level markers
- Git observation

### Inferred hints

Derived but non-authoritative hints:

- stack_hints

For example, package.json can produce a node hint and pyproject.toml can produce a python hint. Hints are not stored inside observed facts.

### Source identity

For a Git project that is inside a work tree:

- kind = git
- branch
- HEAD
- dirty

For a non-Git source the identity remains bounded to the registered source kind and root.

### Capabilities

A snapshot of bounded local capability observations.

### Task

The explicit read-only TaskIntent.

### Provenance

network_used is computed from the included observations. CP-03A context creation performs no network request.

## Capability model expansion

The local capability snapshot now contains:

- python
- git
- node
- sqlite
- local_qwen
- hermes

Python/Git/Node are locally version-probed and can be READY, UNAVAILABLE, or NEEDS_ATTENTION.

SQLite is READY through the local Python stdlib sqlite3 runtime.

local_qwen and hermes are presence-only at CP-03A:

- AVAILABLE means local evidence was found;
- UNAVAILABLE means no bounded local evidence was found;
- neither is reported READY because no readiness/live execution probe is performed.

Presence detection does not invoke Qwen or Hermes.

Bounded local-Qwen evidence may come from:
- a standard local Hugging Face Qwen Instruct GGUF cache entry;
- a locally installed llama-server binary/path.

Bounded Hermes evidence may come from:
- a local hermes/hermes-agent executable;
- ~/.hermes/hermes-agent.

No recursive home scan is performed.

## Status semantics

The overall runtime still reports:

- ai = NOT_INTEGRATED
- worker = NOT_INTEGRATED

even if local_qwen or hermes capability state is AVAILABLE.

This distinction is intentional:

- AVAILABLE = local evidence exists;
- READY = a local capability has passed the checkpoint's readiness contract;
- INTEGRATED = the XP workflow can actually use it.

CP-03A does not claim AI/worker integration.

## Developer CLI

The new context surface is:

- xp-next project context --goal TEXT --intent inspect
- xp-next project context --goal TEXT --intent analyze
- xp-next project context --goal TEXT --intent explain

An optional project id may be supplied; otherwise the current project is used.

This remains a developer/recovery surface. PWA remains the future primary interface.

## TDD evidence

Tests were authored before implementation.

Expected RED state included:

- missing xp_next.task_contract;
- missing xp_next.project_context;
- expanded capability set not implemented;
- status still at CP-02B.

After implementation, the first GREEN run exposed two stale expectations:
- old status test expected ai = NOT_INTEGRATED while the implementation had temporarily used a detected-only status label;
- old project-service test expected only Python/Git/Node capabilities.

The runtime semantics were simplified so ai/worker remain NOT_INTEGRATED until actual integration exists, and the capability expectation was updated to the six bounded local capability ids.

Final suite passed.

## Safety boundaries

CP-03A:

- uses fixture projects only for end-to-end acceptance;
- does not register or inspect Segeran Jiwa;
- does not mutate project source;
- does not execute Qwen reasoning;
- does not execute Hermes;
- does not probe 9Router;
- does not perform any cloud/provider request;
- imports no legacy xp runtime;
- contains no WAITING_GPT or XP_GPT runtime path;
- does not change schema version;
- does not activate the default ~/.xp-next user home during checkpoint automation;
- does not touch a production database;
- does not deploy production.

## Roadmap position

Completed foundation chain:

CP-00A Freeze
-> CP-00B Selective Reuse
-> CP-01A Skeleton
-> CP-01B State Store
-> CP-02A Local Runtime + Project Registry
-> CP-02B Local Inspection + Capability Foundation
-> CP-03A ProjectContext + Read-Only Task Contract

The next boundary is the start of intelligence wiring. It must still remain read-only before any worker mutation is introduced.

## Next allowed checkpoint

CP-04A — Local Qwen Read-Only Reasoning Contract.

Scope must remain narrow:

- define provider-neutral reasoning request/result contracts;
- bind the detected local-Qwen path through an explicit local adapter;
- perform a local readiness check only when explicitly invoked;
- execute one bounded read-only reasoning task against fixture ProjectContext;
- no Hermes execution;
- no project mutation;
- no online provider;
- no 9Router fallback;
- no silent provider/model switch;
- verifier for the reasoning result structure;
- commit, push, verify remote SHA, then stop.
