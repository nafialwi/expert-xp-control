# AF-08 Hybrid Intelligence & Multi-AI Routing — Final Evidence

Date: 2026-09-19

## Identity
- Canonical entry baseline: `4a8d88d9713989006769922e513e5ce0656dd65e`
- AF-08 branch: `work/af08-hybrid-multi-ai-routing`
- Implementation HEAD before evidence: `d9d9d8138ede06dd0e594263dbcaa7cf7fc24043`

## Verified policy
- deterministic tasks remain deterministic;
- explicit provider/model/worker selection;
- no automatic provider ranking;
- no silent provider/model switch;
- no silent fallback after selected-route failure;
- readiness and NOT_CHECKED semantics enforced;
- quota exhaustion => NEEDS_ATTENTION;
- paid/unknown-cost routes require explicit approval;
- privacy/offline gates;
- cloud source analysis requires explicit LIVE;
- mutation routing requires WORKER mode + permission;
- provider/model identity visible;
- source provenance independent from provider/model;
- provider failures classify quota/auth/temp/timeout/generic;
- router evaluation performs no network access.

## Live boundary
- explicit loopback observation is informational only;
- no background probe was added;
- no live inference is required for closure;
- AF-05 already established real inference;
- AF-09 owns real conversational project execution.

## Safety
- AF-07 governed worker safety remains authoritative for mutation.
- No production deployment.
- No database migration.
- No credential persistence.

AF08_STATUS=CLOSED_VERIFIED
NEXT=AF09_CONVERSATIONAL_PROJECT_ORCHESTRATION_REAL_PROJECT_PILOT
