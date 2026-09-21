# CP-08D — Lightweight Local Execution Path

Status: PASS

Base:
- branch: planning/xp-next-bootstrap
- base HEAD: 9f60f658aa48ce38ef23733e7a27219e729f398e
- CP-08C local reasoning quality gate: PASS
- stable XP 2.1.0 source: untouched

## Goal

Provide a fast deterministic local worker for simple bounded file operations so
XP Next does not require the 64k Hermes path for every sandbox mutation.

Hermes remains available as a separate higher-capability worker. CP-08D does
not silently replace it and does not introduce automatic routing.

## Lightweight worker

LightweightLocalWorker implements the existing XP Next worker result/readiness
contract and performs direct Python file I/O inside the already-isolated
workspace.

It does not invoke:
- a language model;
- a shell;
- a subprocess;
- a network transport;
- Git remotes;
- production systems.

Its worker identity is:
- backend: lightweight_local
- model transport: none
- containment: isolated_workspace_direct_file_io

## Explicit operation contract

The worker accepts exactly one JSON operation per WorkerRequest.

Supported CP-08D operations:

### replace_text

Requires:
- safe relative path;
- existing regular UTF-8 text file;
- exact expected_text match;
- bounded new_text;
- actual content change.

### create_text

Requires:
- safe relative path;
- target does not already exist;
- parent directory already exists;
- bounded UTF-8 text.

The worker rejects:
- free-form/prose instructions;
- absolute paths;
- .. traversal;
- .git mutation;
- common credential/environment filenames;
- symlink targets or symlink parents;
- unknown operation fields;
- expected-content mismatches;
- no-op replacement.

All failures become NEEDS_ATTENTION. No fallback worker/provider is selected
inside this component.

## E2E integration

ZeroCostE2EService no longer hardcodes Hermes as the only worker identity.
It reads the selected worker's declared backend/readiness and records that
backend in the Activity Trail.

Existing Hermes behavior remains covered by the regression suite.

A new full fixture E2E proves:

goal
-> fixture local reasoning
-> bounded plan
-> explicit sandbox approval
-> lightweight_local exact text replacement
-> sandbox verifier
-> human review
-> explicit Apply
-> recovery point
-> post-Apply verification
-> COMPLETED

The test confirms the Activity Trail records lightweight_local and does not
mislabel the operation as Hermes.

## Acceptance evidence

Targeted worker/review/apply suite:
- 31 tests PASS.

Full XP Next regression:
- 109 tests PASS.
- zero failures.
- git diff --check PASS.

The new worker-specific coverage verifies:
- deterministic readiness;
- exact bounded replacement;
- create-only semantics;
- prose rejection;
- path traversal rejection;
- .git and sensitive-file rejection;
- expected-content freshness guard;
- symlink rejection;
- no Apply-to-original inside the worker.

## Development failure evidence

The first CP-08D E2E test failed closed because the newly added verifier test
string contained an under-escaped newline. The sandbox change itself was
correct, but verification returned NEEDS_ATTENTION.

The verifier fixture was corrected to represent the intended literal newline,
and the targeted suite then passed 31/31. The final full regression passed
109/109.

No failed run was accepted as success.

## Safety boundaries

CP-08D does not:
- auto-route between workers;
- convert free-form AI text directly into filesystem commands;
- mutate original projects from the worker;
- deploy;
- migrate production data;
- touch Segeran Jiwa projects;
- use paid API, cloud AI, or 9Router;
- weaken review, Apply, recovery, rollback, or post-Apply verification.

The explicit JSON operation must still execute inside a sandbox and pass the
normal XP Next human review/Apply path before reaching an original project.

## Remaining work

CP-08D solves the worker-execution cost for simple deterministic edits, but it
does not yet decide which worker should handle a request.

The next bounded checkpoint should add explicit resource/capability-aware worker
selection with no silent provider switching. It should prefer the lightweight
worker only for operations that can be represented by its strict contract and
leave higher-capability work for explicitly selected agentic workers.
