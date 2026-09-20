# XP Next

XP Next is a fresh, zero-cost-first local AI work system under active construction.

Current checkpoint: CP-07A.

Implemented so far:
- canonical JobState and persistent SQLite StateStore;
- canonical local runtime-home layout and project registry;
- bounded read-only project inspection and local capability registry;
- bounded ProjectContext and read-only TaskIntent;
- provider-neutral local-Qwen reasoning;
- deterministic bounded read-only planner;
- governed Hermes worker in an isolated fixture workspace;
- secret filtering, isolated HOME/TMP, no sandbox Git remote, and file-only worker tools;
- sandbox verification with PASS / FAIL / UNVERIFIED;
- bounded human-readable ReviewBundle;
- immutable review fingerprints for sandbox contents and verifier specs;
- guarded Apply from a PASS, non-truncated, still-fresh review;
- original HEAD + clean-worktree stale-source gate before mutation;
- bounded regular-file copy/delete only;
- recovery manifest created before Apply;
- post-Apply verification against the original;
- automatic rollback on post-Apply failure;
- manual rollback guarded by the exact applied-worktree fingerprint;
- Discard that leaves the original project untouched.

CP-07A is fixture-only and Git-only. Apply never commits, pushes, deploys, or
runs database migrations. The recovery source is the unchanged original Git HEAD
plus a local recovery manifest; HEAD changes invalidate rollback.

The SQLite recovery_points table is not yet wired to the CP-07A filesystem
recovery manifest. End-to-end state-machine persistence belongs to the next
integration checkpoint.

Production projects, Segeran Jiwa, 9Router/cloud fallback, PWA, connectors, and
production actions remain intentionally unavailable to this Apply path.
