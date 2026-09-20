# XP Next — CP-02B Local Project Inspection + Capability Registry

Status: SAFE CHECKPOINT
Date: 2026-09-20
Parent: e2b37f926c186d06b12cade990d2df05390f2ea1

## Purpose

Give XP Next a bounded local ability to observe the device and a registered project without AI, networking, or project mutation.

## Local capability registry

The first capability foundation observes only:

- python
- git
- node

Each observation reports:

- capability id;
- READY, UNAVAILABLE, or NEEDS_ATTENTION;
- executable path when found;
- local version when the version probe succeeds;
- source = local;
- network_used = false.

Version probes execute only the local binary with --version. No internet/provider probe is performed.

A found binary whose local version probe fails is not reported READY; it becomes NEEDS_ATTENTION.

Qwen, Hermes, 9Router, cloud AI, Android tooling, connectors, and device agents are deliberately not represented as ready capabilities in this checkpoint.

## Bounded project inspection

ProjectInspector observes only known top-level markers:

- .git
- package.json
- pyproject.toml
- requirements.txt
- tests/
- src/

It does not recursively search arbitrary dependency/vendor trees to infer project type.

Initial stack hints:

- node when package.json exists;
- python when pyproject.toml or requirements.txt exists.

Inspection always reports network_used = false.

## Git observation

When a .git marker exists and Git is locally available, the inspector may observe:

- whether the path is a Git work tree;
- branch when attached;
- HEAD when resolvable;
- dirty/clean status.

All Git subprocesses are local and use:

- GIT_TERMINAL_PROMPT=0
- GIT_OPTIONAL_LOCKS=0
- bounded timeout

This prevents credential prompting and disables optional Git locks/index refresh behavior during inspection.

No fetch, pull, push, remote query, or network action exists in this inspector.

## Project service integration

ProjectService.inspect(project_id) inspects a registered project.

If project_id is omitted, the current active project is inspected.

The returned observation includes project identity plus bounded project facts.

Registration and inspection remain separate: inspection does not modify project source.

## Status integration

status(home) now reports:

- phase = CP-02B;
- local_capabilities;
- active_project_inspection when there is an active project;
- network_probe_performed = false;
- AI = NOT_INTEGRATED;
- worker = NOT_INTEGRATED.

This is observed local state, not a declaration that XP can yet reason or execute work.

## Developer CLI

New developer surfaces:

- xp-next capabilities
- xp-next project inspect
- xp-next project inspect PROJECT_ID

These remain development/recovery surfaces, not the intended final consumer UI.

## Persistence decision

CP-02B deliberately does not persist capability/project observations.

Reason: schema v1 migration support is not implemented yet. Adding observation tables without a schema-version migration would weaken the state authority contract.

At this checkpoint:

- registered project identity is persistent;
- inspection/capability facts are recomputed locally when requested.

Observation persistence can be introduced only together with an explicit schema migration design.

## TDD and error evidence

Tests were created before implementation.

First command issue:
- a Python edit helper inside the tests-first shell command had an unterminated string literal;
- the command stopped before source implementation;
- recovery audit confirmed HEAD unchanged and only two untracked test files existed.

After resuming tests-first cleanly, the expected RED state was observed:
- missing xp_next.capability_registry;
- missing xp_next.project_inspector;
- ProjectService had no inspect method;
- status still reported CP-02A.

The first GREEN implementation run then exposed one stale legacy test assertion that still expected CP-02A. The implementation behavior was correct; the stale assertion was updated to CP-02B and extended to assert observed capabilities/project inspection.

Final suite then passed.

## Safety boundaries

CP-02B:

- uses only fixture projects for acceptance;
- does not register or inspect Segeran Jiwa;
- performs no project mutation;
- performs no AI call;
- performs no cloud/provider call;
- imports no legacy xp runtime;
- contains no WAITING_GPT or XP_GPT runtime path;
- does not call Qwen, Hermes, or 9Router;
- does not change schema version;
- does not use Supabase as XP operational state;
- does not touch a production database;
- does not deploy production.

## Next allowed checkpoint

CP-03A — Capability Model Expansion + Local Project Context Contract.

Remain read-only and local:

- define a bounded project-context object from registered identity + inspection facts;
- distinguish observed facts from inferred hints;
- add local readiness entries for SQLite/runtime and later local-Qwen/Hermes presence detection without invoking them;
- define the first read-only task/intention contract;
- do not perform AI reasoning yet;
- do not execute Hermes;
- do not mutate a project;
- use fixtures only;
- commit, push, verify remote SHA, then stop.

## Finalization recovery note

An initial finalization smoke completed the full 36-test suite and produced correct capability/project inspection output, but a shell-level assertion later in the smoke returned non-zero before commit. Recovery audit showed:

- branch HEAD still at the CP-02A parent;
- no commit or push had occurred;
- only intended CP-02B source/test/doc changes were present;
- the temporary fixture Git HEAD was unchanged and its worktree remained clean.

The final acceptance was rerun with structured Python/JSON assertions instead of fragile text-grep assertions before committing the checkpoint.
