# CP-08C — Local Reasoning Quality Gate

Status: PASS

Base:
- branch: planning/xp-next-bootstrap
- base HEAD: 58c0ecfdb2c4b7428c99a5aef16959d7538282d3
- CP-08B runtime characterization: NEEDS_ATTENTION
- stable XP 2.1.0 source: untouched

## Goal

Prevent XP Next from accepting obviously malformed local-model text merely
because transport succeeded and the response was non-empty.

CP-08B proved that the real Qwen 0.5B runtime could satisfy the mechanical
adapter contract while still returning fragmented/repetitive output. CP-08C
adds a deterministic local sanity gate and keeps fail-closed behavior.

## Quality gate

assess_reasoning_quality() now rejects bounded classes of unusable output:

- control-character noise;
- excessive structured-symbol noise;
- symbol-dominated text;
- severe low-diversity token repetition;
- one-token domination;
- repeated-token loops.

The gate is deliberately narrow. It is not a truth checker, semantic judge, or
hidden model evaluator. It does not claim that accepted text is factually
correct. It only prevents known pathological output shapes from being promoted
to COMPLETED.

The LocalQwen prompt also requests 1–3 concise plain-text sentences and
explicitly rejects JSON, code, and repeated filler tokens.

## Adapter behavior

If the transport returns a response that fails the deterministic quality gate,
LocalQwenAdapter.reason() returns:

- status: NEEDS_ATTENTION
- output: empty
- backend: local_qwen
- transport: loopback_http
- no external-network claim
- an explicit quality failure detail

No alternate provider or paid/cloud fallback is attempted.

## Tests

New contract coverage verifies that:

- short useful plain text passes;
- repeated-token loops fail;
- symbol-dominated output fails;
- the fragmented shape observed from the real Qwen 0.5B run fails;
- a model response that is mechanically complete but pathological becomes
  NEEDS_ATTENTION in the adapter.

Existing zero-cost, planner, and E2E contracts remain intact.

## Real runtime acceptance

The real Qwen2.5 0.5B Q4_K_M model on loopback port 18085 was exercised after
the quality gate was installed.

Three small context-grounded prompts were attempted:

1. report the Python stack hint;
2. report Git branch main;
3. report project name Fixture.

Observed result:

- accepted: 0
- rejected as NEEDS_ATTENTION: 3
- two were rejected for excessive structured-symbol noise;
- one was rejected for excessive token repetition.

This is the intended fail-closed result. Before CP-08C, one similarly malformed
response was incorrectly accepted as COMPLETED.

## Safety

CP-08C:

- does not loosen any CP-08A/CP-07A apply, recovery, review, or rollback guard;
- does not use Segeran Jiwa as a test fixture;
- does not deploy anything;
- does not migrate a production database;
- does not require paid API, cloud AI, or 9Router;
- does not silently switch model/provider;
- does not expose hidden chain-of-thought.

## Remaining gap

The current 0.5B model is still not useful enough for the local reasoning role,
and Hermes remains too slow under the current 64k worker contract on this PC.

The next bounded runtime-usability checkpoint should evaluate a lighter local
execution path for simple bounded file operations while keeping Hermes
optional for higher-capability work when resources permit.
