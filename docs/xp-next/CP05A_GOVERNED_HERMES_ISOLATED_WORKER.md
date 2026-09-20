# XP Next — CP-05A Governed Hermes Isolated Worker

Status: SAFE CHECKPOINT
Date: 2026-09-20
Parent: 4e4605fdd8bb90cdf7a2b2ecd8035ab31ac17856

## Purpose

Introduce the first write-capable worker boundary without allowing writes to the
registered/original project.

CP-05A is intentionally fixture-only and zero-cost-first.

The flow is:

original fixture
-> bounded isolated copy
-> fresh local Git baseline with no remote
-> isolated HOME/TMP
-> local Hermes
-> loopback local model
-> file-only mutation inside the isolated copy
-> mutation audit
-> original-integrity check

There is no Apply step in this checkpoint.

## Worker contract

CP-05A adds:

- WorkerStatus
- WorkerReadiness
- WorkerRequest
- WorkerResult
- HermesLocalWorker

WorkerRequest is valid only when:

- scope = isolated_workspace;
- cwd exists inside workspace_root;
- mutation_allowed = true for sandbox-only mutation;
- apply_to_original_allowed = false;
- production_allowed = false;
- prompt is non-empty and bounded.

WorkerResult always records whether an original-project apply was performed.
CP-05A keeps that value false.

## Isolated workspace

prepare_isolated_workspace():

- refuses an empty job id;
- resolves the source root explicitly;
- refuses a sandbox rooted inside the source project;
- creates separate project/home/tmp directories;
- copies a bounded number/size of files;
- refuses source symlinks;
- skips .git, caches, node_modules, and known credential filenames;
- creates a fresh local Git repository in the sandbox;
- configures local sandbox Git identity;
- disables Git hooks through core.hooksPath=/dev/null;
- creates a baseline commit;
- requires the sandbox to have no Git remote.

The original project is not modified by workspace preparation.

## Hermes binding

Observed local Hermes:

- Hermes Agent v0.21.3 (2026.9.14);
- local executable available;
- no update was performed during this checkpoint.

The worker is bound only to an http://127.0.0.1/.../v1 or loopback equivalent.
Remote model endpoints are rejected by construction.

The worker creates an isolated Hermes config and environment:

- HOME = sandbox home;
- HERMES_HOME = sandbox home/.hermes;
- TMPDIR = sandbox tmp;
- no inherited arbitrary environment secrets;
- local placeholder API key only;
- model endpoint = loopback only;
- external HTTP/HTTPS/ALL proxy values point to a dead loopback proxy;
- NO_PROXY permits only loopback/localhost;
- MCP servers disabled;
- connectors disabled;
- memory/user-profile disabled;
- tool search disabled;
- project AGENTS/SOUL/rule injection disabled with --ignore-rules.

Only the Hermes file toolset is enabled in this checkpoint.
The terminal toolset is not enabled.

Hermes turn budget is explicitly bounded through agent.max_turns: 2.

The worker also has a finite wall timeout. On this development device the
default is 480 seconds because the local 1.5B model is slow at Hermes-sized
prompts.

## Context-size finding

Hermes refused the local model when effective context was below its 64k floor.

The installed Qwen2.5 1.5B GGUF reports a 32,768-token training context. Starting
llama-server with -c 65536 alone was capped back to 32,768.

For the fixture acceptance only, llama-server was started with YaRN scaling:

- context requested: 65,536;
- rope scaling: yarn;
- rope scale: 2;
- original context: 32,768.

The resulting /props effective context was 65,536 and Hermes readiness passed.

This does not mean extended-context quality has been proven. It only establishes
that the local worker can satisfy Hermes's runtime context requirement for this
fixture. Automatic model lifecycle/scaling policy is not part of CP-05A.

## Live acceptance

A fresh fixture was created with:

- one original text file;
- one .env secret fixture;
- local Git baseline.

The worker task was deliberately trivial:

- create proof.txt;
- exact contents XP_HERMES_SANDBOX_OK plus newline;
- do not modify/delete existing files.

Observed final run:

- Hermes readiness = READY;
- effective local model context = 65,536;
- worker result = COMPLETED;
- return code = 0;
- changed sandbox paths = exactly proof.txt;
- proof contents = exact expected bytes;
- .env was not copied into the sandbox;
- sandbox Git remote = absent;
- apply_to_original_performed = false;
- original Git HEAD unchanged;
- original Git status unchanged;
- original non-Git file hash unchanged;
- temporary llama-server stopped;
- elapsed Hermes worker time = 312 seconds.

Therefore the CP-05A fixture acceptance passed.

## Tests

Final deterministic suite before checkpoint commit:

- 73 tests;
- all PASS.

The tests cover, among other things:

- worker request scope validation;
- cwd must be inside isolated root;
- production/original apply forbidden by contract;
- remote model URL rejection;
- readiness fail-closed behavior;
- minimum effective context requirement;
- environment-secret non-inheritance;
- disabled tool search/connectors;
- no-mutation result becomes NEEDS_ATTENTION;
- worker cwd is isolated;
- file-only toolset;
- --ignore-rules;
- no original apply;
- isolated copy has no remote;
- sensitive filename filtering;
- source symlink rejection;
- sandbox diff detection.

## Important containment limitation

CP-05A is not an OS-level sandbox.

The containment label is intentionally:

isolated_copy_sanitized_env_best_effort_network_block

The local Hermes process still runs as the Termux user. The file tool has its own
safety checks, and XP limits normal operation to the isolated cwd, but CP-05A
does not yet prove a kernel-enforced filesystem jail. Likewise, dead proxy
variables are a best-effort external-network block rather than a kernel firewall.

For that reason:

- CP-05A is accepted only for the isolated fixture boundary;
- it must not run against Segeran Jiwa or another production project yet;
- it must not receive production credentials;
- no database/deploy/push operation is allowed;
- a worker timeout remains NEEDS_ATTENTION even if a sandbox mutation happened;
- no sandbox result is automatically applied to the original source.

Harder containment can be added later without changing the WorkerRequest /
WorkerResult contract.

## Findings during development

Several fail-closed tests found real integration details:

1. Hermes requires at least ~64k effective context for this path.
2. Qwen2.5 1.5B's native 32k context is capped by llama-server unless explicit
   context scaling is configured.
3. agent.max_iterations was not the authoritative Hermes config key.
   The actual current key is agent.max_turns.
4. Passing --max-turns in the initial one-shot argument position was rejected
   by the installed CLI, so CP-05A uses the isolated config as the turn-budget
   authority.
5. A 360-second worker timeout was too short on the development device even
   though the requested sandbox file had already been written correctly.
   The result correctly failed closed as NEEDS_ATTENTION.
6. With the bounded two-turn config and a 480-second wall timeout, the same
   isolated fixture completed successfully in 312 seconds.

No failed experiment was treated as success.

## Boundaries retained

CP-05A:

- does not mutate a registered/original project;
- does not Apply a sandbox diff;
- does not commit/push/deploy user projects;
- does not use 9Router;
- does not use paid/cloud AI;
- does not silently change provider/model;
- does not touch Segeran Jiwa;
- does not touch production databases;
- leaves XP+ 2.1.0 stable unchanged.

## Next allowed checkpoint

CP-06A — Sandbox Verification + Human Review Bundle.

Narrow scope:

- run deterministic verifier(s) against the changed sandbox;
- capture changed-file list and bounded diff;
- distinguish PASS / FAIL / UNVERIFIED;
- produce a human-readable review bundle;
- keep original project unchanged;
- no Apply/Discard implementation yet;
- no push/deploy/database actions;
- commit and push the checkpoint, verify remote SHA, then stop.
