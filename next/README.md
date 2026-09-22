# XP Next

XP Next is a fresh, zero-cost-first local AI work system under active construction.

Current checkpoint: CP-08H.

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

The guarded Apply core remains Git-only. Apply never commits, pushes, deploys,
or runs database migrations. The recovery source is the unchanged original Git
HEAD plus a local recovery manifest; HEAD changes invalidate rollback.

The reviewed work path may target a registered Git project, but only through the
isolated local worker + verifier + Apply/Discard controls. Production deployment,
production database migration, mandatory cloud/9Router fallback, and silent
worker substitution remain intentionally unavailable.


## CP-08H human-friendly work flow

`xp-next work` composes the existing local project context, worker selection,
explicit human confirmation, isolated execution, verifier review, and guarded
Apply/Discard path into one user-facing command. It remains local-first and
fail-closed: no silent worker fallback, no Apply without a PASS review, no
automatic commit/push/deploy, and no production database action. A canonical
`npm run verify` script can be discovered automatically; other projects must
provide an explicit verifier command.
