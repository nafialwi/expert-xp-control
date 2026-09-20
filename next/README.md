# XP Next

XP Next is a fresh, zero-cost-first local AI work system under active construction.

Current checkpoint: CP-04B.

Implemented so far:
- canonical JobState contract;
- SQLite schema v1 and persistent StateStore;
- canonical local runtime-home layout;
- local project registry and bounded read-only project inspection;
- local capability registry for Python, Git, Node, SQLite, local Qwen, and Hermes presence;
- bounded ProjectContext with observed facts separated from inferred hints;
- read-only TaskIntent contract;
- provider-neutral read-only reasoning request/result contracts;
- loopback-only LocalQwenAdapter with explicit readiness;
- compact local reasoning context;
- bounded deterministic read-only Plan/PlanStep contract;
- structural plan verifier;
- model-output isolation: AI text cannot create executable plan-step kinds;
- one-snapshot planning: context is built once and reused for reasoning + plan;
- explicit NEEDS_ATTENTION with no provider fallback;
- zero-cost independence acceptance fixture.

At CP-04B, Qwen can reason over bounded local context and XP can compile a verified
read-only plan. The planner does not execute tools and cannot mutate a project.

Hermes execution, sandbox mutation, Review/Apply/Discard, 9Router, cloud fallback,
PWA, connectors, and production actions are intentionally not integrated yet.
