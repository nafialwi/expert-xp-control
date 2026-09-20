# XP Next — CP-02A Canonical Local Runtime + Project Registry

Status: SAFE CHECKPOINT
Date: 2026-09-20
Parent: 600f6b0a3254d6b18ea3bdde4d8b1d94534271f4

## Purpose

Activate the first local XP Next runtime composition around the CP-01B SQLite state store without introducing AI, workers, networking, PWA, connectors, or real production projects.

## Canonical runtime home

XP Next now resolves its runtime home in this order:

1. explicit home passed by the caller;
2. XP_NEXT_HOME;
3. ~/.xp-next.

Runtime layout:

- state/xp-next.sqlite3
- artifacts/
- workspaces/
- logs/

The runtime root and managed subdirectories fail closed if they are symbolic links. Directories are created with private POSIX permissions where supported.

Checkpoint automation used temporary runtime homes only. It did not create or populate the user's default ~/.xp-next home.

## Runtime composition

XPRuntime.open(home) now:

1. resolves the runtime paths;
2. safely creates the runtime directory layout;
3. opens/initializes the local SQLite StateStore;
4. exposes the store to bounded services;
5. closes the store deterministically through context-manager use.

No network request is part of runtime activation.

## Local project service

ProjectService now supports:

- register a local project;
- list registered projects;
- switch the active project;
- read the current active project.

Registration requires the project root to exist and be a directory before any database write occurs. Stored paths are absolute resolved paths.

Supported source kinds at this checkpoint are local and git.

The SQLite schema also constrains source kind to those values.

No project source is modified by registration or switching.

## State-backed status

status(home) now opens the selected local runtime state and reports:

- product/version;
- phase = CP-02A;
- runtime = LOCAL_STATE_ACTIVE;
- database = READY;
- project count;
- active project;
- AI = NOT_INTEGRATED;
- worker = NOT_INTEGRATED;
- network_required = false.

This is intentionally honest: local state is active, but intelligence and execution are not.

## Developer CLI

The developer CLI now accepts a runtime home override and local project operations:

- xp-next --home PATH status
- xp-next --home PATH project register --id ID --name NAME --root PATH
- xp-next --home PATH project list
- xp-next --home PATH project switch ID
- xp-next --home PATH project current

The default remains XP_NEXT_HOME or ~/.xp-next when no explicit home is passed.

The PWA remains the intended primary user interface later. This CLI is a development/recovery surface.

## TDD evidence

CP-02A tests were written before implementation.

Expected RED result:

- missing xp_next.runtime_paths;
- missing xp_next.project_service;
- existing status() did not yet accept a runtime home.

After minimal implementation, the complete XP Next suite passed.

## End-to-end local smoke

A temporary runtime home and two temporary project directories were created.

The smoke flow executed in separate CLI processes:

1. status on a fresh runtime;
2. register project p1;
3. register project p2;
4. switch active project to p2;
5. list projects;
6. read current project;
7. open status again.

Final status reported project_count = 2, active_project = p2, database = READY, and runtime = LOCAL_STATE_ACTIVE.

The temporary runtime/project directories were deleted after the smoke.

## Safety guarantees retained

CP-02A:

- imports no legacy xp runtime;
- contains no WAITING_GPT or XP_GPT runtime path;
- performs no AI request;
- performs no cloud request;
- does not call Qwen;
- does not call Hermes;
- does not call 9Router;
- does not use Supabase as XP operational state;
- does not register or mutate Segeran Jiwa;
- does not run a production database migration;
- does not deploy production.

## Tests

At implementation completion before final checkpoint commit:

Ran 28 tests ... OK

The suite covers previous state/schema contracts plus canonical runtime-home layout, environment override, runtime directory creation, symlink-root fail-closed behavior, local project registration, missing-root fail-before-write, resolved project paths, list/switch/current behavior, process-restart persistence, and state-backed status.

## Known limitations

Not implemented yet:

- project auto-discovery;
- Git fingerprint capture;
- project verifier discovery in XP Next;
- project onboarding recommendations;
- Activity Trail persistence service;
- approval/recovery/artifact service APIs;
- cross-process lease/expiry;
- AI reasoning;
- Hermes worker;
- sandbox;
- verifier execution;
- Review / Apply / Discard;
- PWA.

## Next allowed checkpoint

CP-02B — Local Project Inspection + Capability Registry Foundation.

Keep it read-only and local:

- inspect registered project facts without changing source;
- detect basic Git/Python/Node availability and project markers;
- persist observed local capabilities/project facts where appropriate;
- expose them through status/project inspection;
- no AI, Hermes, 9Router, network probes, PWA, or project mutation;
- use fixture projects only;
- commit, push, verify remote SHA, then stop.
