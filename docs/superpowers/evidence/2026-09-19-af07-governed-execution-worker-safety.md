# AF-07 Governed Execution & Worker Safety — Closure Evidence

Date: 2026-09-19

## Entry
- Canonical base: `8fc134e268224558f61b9ae64bbc5d031539a877`
- AF-07 implementation commit: `946208cc43d9a14fb074912e7da480ceea98045a`

## Deterministic safety gates
- Approval classes implemented: READ_ONLY / WRITE_ALLOWED / HIGH_RISK_CONFIRM.
- Workspace boundary and cwd permission separation verified.
- Worker readiness gate verified.
- Recovery-before-execution verified.
- Mutation audit verified.
- READ_ONLY unauthorized mutation fail-closed + rollback verified.
- Verifier authority verified.
- Bounded remediation verified.
- Protected canonical repository integrity guard verified.
- Activity Trail records observable actions/results without hidden reasoning.
- Focused AF-07 tests passed.
- Full XP regression passed.

## Real Hermes LAB evidence
A real HermesPilotRuntime run was governed inside HERMES-LAB.

Observed:
- readiness: READY;
- explicit LAB-only WRITE_ALLOWED scope;
- real mutation detected: `xp-hermes-pilot-usage.json`;
- worker returned code 124;
- verifier failed;
- governed result became `NEEDS_ATTENTION`;
- no fake success;
- Activity Trail recorded approval/readiness/recovery/execution/mutation/verifier;
- HERMES-LAB outer restore passed;
- canonical XP remained unchanged.

This is accepted as AF-07 real-worker **failure-containment evidence**.

The successful live Hermes positive path is intentionally deferred to AF-08,
because provider latency/quota/routing/live-worker availability belongs to
Hybrid Intelligence & Multi-AI Routing, not the AF-07 safety invariant.

## Closure
AF07_STATUS=CLOSED_VERIFIED
AF07_HERMES_FAILURE_CONTAINMENT=PASS
AF07_HERMES_POSITIVE_PATH=DEFERRED_AF08
NEXT=AF08_HYBRID_INTELLIGENCE_AND_MULTI_AI_ROUTING
