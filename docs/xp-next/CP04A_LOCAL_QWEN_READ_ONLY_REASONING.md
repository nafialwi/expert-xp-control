# XP Next — CP-04A Local Qwen Read-Only Reasoning

Status: SAFE CHECKPOINT
Date: 2026-09-20
Parent: a001a428e2793e03fb9790759bf0b94a7e347f4e

## Purpose

Prove that XP Next can use a local zero-cost Qwen model for one bounded read-only reasoning task without ChatGPT, paid APIs, 9Router, cloud fallback, Hermes, or project mutation.

## Provider-neutral reasoning contract

CP-04A adds:

- ReasoningRequest
- ReasoningResult
- ReasoningStatus
- deterministic verify_reasoning_result()

ReasoningRequest accepts only the CP-03A read-only TaskIntent contract.

It rejects:
- non-read risk;
- mutation-enabled tasks;
- tasks that allow network access;
- context that already reports network use;
- oversized context;
- unbounded output token requests.

ReasoningResult records:
- COMPLETED or NEEDS_ATTENTION;
- output;
- backend id;
- model;
- transport;
- external-network provenance;
- bounded diagnostic detail.

A completed result is not accepted by the verifier if output is empty, transport is unexpected, the backend is not local_qwen, external-network use is reported, or output exceeds the bounded size.

## Compact reasoning context

The full ProjectContext is not sent verbatim to the local model.

compact_reasoning_context() preserves only the bounded semantic facts needed for CP-04A:
- project id/name/source kind;
- source identity;
- observed markers and Git facts;
- inferred stack hints;
- capability state/version;
- network provenance.

Runtime paths, executable paths, capability evidence paths, and other local implementation noise are removed.

This reduced the prompt cost for constrained mobile hardware while preserving the source facts required by the task.

## LocalQwenAdapter

The adapter:
- accepts only HTTP loopback addresses 127.0.0.1 or ::1;
- rejects remote hosts;
- rejects credentials/query/fragment/path in the base URL;
- performs an explicit /health readiness request only when requested by the caller;
- sends read-only reasoning to /v1/chat/completions;
- uses no API key;
- has no provider fallback;
- reports transport failure as NEEDS_ATTENTION;
- never silently switches to 9Router, cloud AI, or another model.

The prompt explicitly instructs the backend to:
- use only the supplied bounded context;
- avoid tool use/file mutation/external network use;
- return concise conclusions;
- not expose hidden chain-of-thought;
- not claim actions it did not perform.

## Runtime status

CP-04A reports:
- phase = CP-04A;
- ai = LOCAL_READ_ONLY_ADAPTER;
- worker = NOT_INTEGRATED.

This means XP has a read-only local reasoning adapter. It does not mean the local server is always running or that AI has write authority.

Capability presence and runtime readiness remain distinct concepts.

## Actual local model evidence

The development device currently contains:
- llama-server at the local Termux executable path;
- Qwen2.5 1.5B Instruct GGUF Q4_K_M;
- Qwen2.5 3B Instruct GGUF Q4_K_M;
- an additional Qwen2.5 7B Instruct GGUF cache directory.

The CP-04A live acceptance used the 1.5B Q4_K_M model to keep the checkpoint bounded.

## Live acceptance

At preflight, 127.0.0.1:8080 had no running llama-server. This was treated correctly as unavailable runtime readiness rather than as a false READY state.

For the acceptance test only, a temporary llama-server was explicitly launched on:
- host 127.0.0.1;
- dedicated port 18080;
- model alias local;
- Qwen2.5 1.5B Instruct Q4_K_M;
- bounded context;
- one parallel slot.

The first live attempt:
- passed local readiness;
- reached the local model;
- returned NEEDS_ATTENTION after the original 45-second client timeout;
- did not fall back to another provider;
- did not mutate the fixture project;
- stopped the temporary server through cleanup.

Server logs confirmed model load and a loopback-only listener. The task was cancelled when the client timeout was reached.

This exposed a real mobile-hardware latency constraint rather than being hidden.

The implementation was then hardened by:
- compacting the reasoning context;
- raising the explicit local-model timeout default to 120 seconds;
- retaining bounded max tokens;
- using one parallel llama-server slot in the live acceptance.

The second live acceptance passed:
- explicit /health readiness = READY;
- local_qwen reasoning status = COMPLETED;
- backend = local_qwen;
- transport = loopback_http;
- external_network_used = false;
- output contained both expected stack hints: node and python;
- reasoning elapsed time = 37 seconds;
- fixture Git HEAD unchanged;
- fixture Git status unchanged;
- temporary llama-server stopped after the test.

Observed output: node python

## TDD evidence

Tests were written before the new reasoning modules.

Expected RED:
- missing xp_next.reasoning;
- missing xp_next.local_qwen;
- runtime phase still CP-03A.

After initial implementation the full suite passed.

A second tests-first hardening cycle introduced compact_reasoning_context. The expected RED import failure was observed before implementation.

Final unit/integration suite at checkpoint:
- 52 tests;
- all PASS.

The live local-Qwen acceptance is separate from the fast deterministic unit suite.

## Safety boundaries retained

CP-04A:
- does not execute Hermes;
- does not allow AI project mutation;
- does not use 9Router;
- does not use paid APIs;
- does not use ChatGPT as a runtime dependency;
- does not use a remote AI endpoint;
- does not silently switch provider/model;
- does not register or inspect Segeran Jiwa;
- does not touch a production database;
- does not deploy production;
- does not change XP+ 2.1.0 stable;
- does not activate a persistent default user project through checkpoint automation.

The temporary llama-server used for acceptance was stopped before the checkpoint was committed.

## Known limitations

Not implemented yet:
- automatic local llama-server lifecycle management;
- streamed reasoning progress;
- cancellation from XP UI;
- read-only Intent Resolver beyond the explicit TaskIntent enum;
- bounded planner;
- Context selection by task relevance beyond the current compact context;
- Hermes worker;
- sandbox;
- verifier for project changes;
- Review / Apply / Discard;
- PWA.

The measured 37-second response for a small local task on the current device is a real UX constraint that later UI/runtime work must surface rather than hide.

## Next allowed checkpoint

CP-04B — Bounded Read-Only Planner.

Remain zero-cost and read-only:
- define a provider-neutral bounded Plan/PlanStep contract;
- transform TaskIntent + ProjectContext + local-Qwen output into a small inspect/analyze/explain plan;
- deterministic structural plan verifier;
- reject mutation/tool-write steps;
- no Hermes;
- no project mutation;
- no 9Router/cloud fallback;
- use fixture project only;
- commit, push, verify remote SHA, then stop.

Only after the read-only reasoning/planning loop is stable should CP-05 introduce a governed Hermes worker.
