# AF-07 — Governed Execution & Worker Safety

Status: **LOCKED IMPLEMENTATION SPEC**

Canonical entry baseline:

`8fc134e268224558f61b9ae64bbc5d031539a877`

Canonical branch:

`work/xp-plus-v1`

Implementation branch:

`work/af07-governed-worker-safety`

## Goal

Create the safety/control layer between XP and any worker runtime.

Hermes is a replaceable worker. `cwd` is context, not permission.

## Required approval classes

- `READ_ONLY`
- `WRITE_ALLOWED`
- `HIGH_RISK_CONFIRM`

## Required gates

1. Explicit approval bound to job + workspace.
2. Workspace/cwd boundary validation.
3. Worker readiness before execution.
4. Recovery point before worker execution.
5. Mutation audit before/after execution.
6. READ_ONLY unauthorized mutation => fail closed + rollback.
7. Verifier result is authoritative.
8. Bounded remediation only; no infinite retry.
9. Failed verification after budget => rollback + `NEEDS_ATTENTION`.
10. Protected canonical XP repository integrity check.
11. Activity Trail records observable actions/results only.
12. No raw prompt, hidden reasoning, secrets, or credentials in Activity Trail.
13. No silent model/provider/worker fallback.
14. Real Hermes validation is LAB-only for AF-07.
15. No production deployment or database migration.

## Completion

AF-07 is closed only when:

- dedicated AF-07 tests pass;
- full XP regression passes;
- fake-worker offline safety suite passes;
- real Hermes LAB governed smoke passes;
- canonical XP repo is unchanged by Hermes LAB smoke;
- AF-07 evidence is committed;
- implementation branch is pushed;
- merge into `work/xp-plus-v1` passes full regression;
- canonical branch push is verified.

Next:

`AF08_HYBRID_INTELLIGENCE_AND_MULTI_AI_ROUTING`
