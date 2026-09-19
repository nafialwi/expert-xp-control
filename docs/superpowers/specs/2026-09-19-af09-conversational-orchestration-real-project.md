# AF-09 — Conversational Project Orchestration + Real Project Pilot

Status: LOCKED IMPLEMENTATION SPEC

Canonical entry baseline:
`b1c6eb698633228580a4c59c75352180483772b8`

Canonical branch:
`work/xp-plus-v1`

Implementation branch:
`work/af09-conversational-orchestration`

## Goal

Turn AF-06 recovery, AF-07 worker governance, and AF-08 hybrid routing into one
bounded project workflow driven by a human-style request.

## Required orchestration sequence

1. identify project + checkpoint;
2. retrieve only relevant context;
3. produce a bounded plan;
4. create recovery before risky mutation;
5. require risk-appropriate approval;
6. choose deterministic tool / AI / worker explicitly;
7. execute;
8. verify;
9. remediate within a bounded budget;
10. rollback when verification cannot be satisfied;
11. stop at a checkpoint;
12. persist observable Activity Trail evidence.

## Acceptance matrix

- generic dummy project;
- selective read-only analysis;
- approval-blocked mutation;
- approved write task;
- failing-verifier remediation;
- remediation exhaustion + rollback;
- isolated Segeran Jiwa POS Next copy;
- original Segeran Jiwa repository integrity preserved;
- canonical XP repository integrity preserved.

## Real project pilot

The pilot uses a temporary local clone of:

`~/WORKSTATION/projects/segeran-jiwa-pos-next`

It never mutates the original project.

No production deploy, database mutation, Firebase mutation, or live AI/provider
success is required for AF-09 closure.

Next:
`AF10_VISUAL_WORKSTATION_AND_AI_FINAL_ACCEPTANCE`
