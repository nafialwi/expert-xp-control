# XP Next

XP Next is a fresh, zero-cost-first local AI work system under active construction.

Current checkpoint: CP-04A.

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
- deterministic reasoning-result verification;
- compact local reasoning context;
- explicit failure as NEEDS_ATTENTION with no provider fallback;
- zero-cost independence acceptance fixture.

Local Qwen integration at CP-04A is read-only. It communicates only with an explicitly invoked
loopback llama-server. Server lifecycle is not yet managed automatically by XP Next.

Qwen project mutation, Hermes execution, 9Router, PWA, connectors, sandbox execution,
Review/Apply/Discard, and production actions are intentionally not integrated yet.
