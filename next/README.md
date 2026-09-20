# XP Next

XP Next is a fresh, zero-cost-first local AI work system under active construction.

Current checkpoint: CP-05A.

Implemented so far:
- canonical JobState contract;
- SQLite schema v1 and persistent StateStore;
- canonical local runtime-home layout;
- local project registry and bounded read-only project inspection;
- local capability registry for Python, Git, Node, SQLite, local Qwen, and Hermes presence;
- bounded ProjectContext with observed facts separated from inferred hints;
- read-only TaskIntent contract;
- provider-neutral local reasoning contracts;
- loopback-only LocalQwenAdapter with explicit readiness;
- compact local reasoning context;
- bounded deterministic read-only Plan/PlanStep contract;
- structural plan verifier;
- model-output isolation: AI text cannot create executable plan-step kinds;
- one-snapshot planning: context is built once and reused for reasoning + plan;
- explicit NEEDS_ATTENTION with no provider fallback;
- CP-05A worker request/readiness/result contracts;
- fixture-only isolated workspace creation with a fresh Git baseline and no remotes;
- secret-name filtering during isolated copy;
- isolated HOME/TMP environment for Hermes with inherited secrets removed;
- loopback-only local-model transport for Hermes;
- Hermes file-only toolset with project-rule injection disabled;
- bounded Hermes turn budget (agent.max_turns: 2);
- finite worker wall timeout;
- post-run sandbox mutation audit;
- no Apply to original project in CP-05A;
- zero-cost independence acceptance fixture.

CP-05A has a live acceptance with Hermes 0.21.3 + local Qwen that creates a
file in the isolated workspace while the original fixture remains byte-for-byte
unchanged. This is not yet a production write workflow.

Verification/review, Apply/Discard/Rollback, automatic local-model lifecycle,
9Router/cloud fallback, PWA, connectors, and production actions are intentionally
not integrated yet.
