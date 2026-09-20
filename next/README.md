# XP Next

XP Next is a fresh, zero-cost-first local AI work system under active construction.

Current checkpoint: CP-06A.

Implemented so far:
- canonical JobState and persistent SQLite StateStore;
- canonical local runtime-home layout and project registry;
- bounded read-only project inspection and local capability registry;
- bounded ProjectContext and read-only TaskIntent;
- provider-neutral local-Qwen reasoning;
- deterministic bounded read-only planner;
- governed Hermes worker in an isolated fixture workspace;
- secret filtering, isolated HOME/TMP, no sandbox Git remote, and file-only worker tools;
- no Apply to original project;
- Sandbox Verification with PASS / FAIL / UNVERIFIED;
- trusted local verifier specs executed without a shell;
- obvious shell/network wrapper verifier commands rejected;
- verifier side effects detected and failed closed;
- bounded changed-file diff with truncation marker;
- structured ReviewBundle plus human-readable review text.

At CP-06A, XP can verify a changed sandbox and produce a review bundle, but it
still cannot Apply or Discard changes in the original project.

Apply/Discard/Rollback, production writes, 9Router/cloud fallback, PWA,
connectors, and production actions remain intentionally unavailable.
