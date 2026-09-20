# XP Next

XP Next is a fresh, zero-cost-first local AI work system under active construction.

Current checkpoint: CP-03A.

Implemented so far:
- canonical JobState contract;
- SQLite schema v1 and persistent StateStore;
- canonical local runtime-home layout;
- local project register/list/switch/current service;
- bounded read-only project inspection;
- local capability registry for Python, Git, Node, SQLite, local-Qwen presence, and Hermes presence;
- explicit separation between READY and presence-only AVAILABLE capability state;
- bounded ProjectContext with observed facts separated from inferred hints;
- first read-only TaskIntent contract;
- local-only status/doctor;
- zero-cost independence acceptance fixture.

Default runtime home:
- XP_NEXT_HOME when explicitly set;
- otherwise ~/.xp-next.

Current runtime-home layout:
- state/xp-next.sqlite3
- artifacts/
- workspaces/
- logs/

Qwen reasoning, Hermes execution, 9Router, PWA, connectors, sandbox execution,
real project mutation, review/apply, and production actions are intentionally not integrated yet.
