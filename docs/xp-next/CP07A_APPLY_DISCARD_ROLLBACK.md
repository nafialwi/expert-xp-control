# XP Next — CP-07A Apply / Discard / Rollback Foundation

Status: SAFE CHECKPOINT
Date: 2026-09-21
Parent: 890a3c72a160b0911d9d9d732756d5f841e3a0f9

## Purpose

Introduce the first controlled mutation of an original fixture project after a
human-reviewable sandbox result has already passed CP-06A verification.

The CP-07A safety order is:

review PASS
-> review freshness check
-> original HEAD/status gate
-> sandbox/original baseline binding
-> recovery point
-> bounded Apply
-> post-Apply verification
-> keep result on PASS
-> automatic rollback on failure

Discard never mutates the original.

## Review freshness

ReviewBundle now contains:

- sandbox_head;
- change_fingerprint;
- verifier_spec_fingerprint.

change_fingerprint binds the reviewed changed-path set and file contents to the
sandbox baseline HEAD.

verifier_spec_fingerprint binds the verifier names, argv, and timeout values.

Before Apply or Discard, XP rebuilds the review and requires:

- approved review status = PASS;
- approved diff is not truncated;
- current review status = PASS;
- current diff is not truncated;
- same sandbox HEAD;
- same changed files;
- same content fingerprint;
- same verifier-spec fingerprint;
- same bounded review diff.

Any mismatch is treated as a stale review and fails before original mutation.

## Original-project gate

CP-07A supports Git working trees only.

Before recovery creation or mutation:

- original HEAD must exactly match expected_original_head;
- original working tree must be clean;
- original and sandbox must be different directories.

If the user changes the original after review, Apply refuses before mutation.

No automatic stash, reset, overwrite, or merge is performed.

## Sandbox-to-original baseline binding

For every reviewed changed path, CP-07A compares the file bytes represented by:

- sandbox baseline HEAD;
- expected original HEAD.

They must match before the sandbox result can be applied.

This blocks a reviewed patch from a sandbox whose relevant baseline does not
match the original project.

## Change bounds

The CP-07A Apply surface is deliberately small:

- maximum 50 changed files;
- maximum 8 MiB for one changed file;
- maximum 16 MiB total changed file content;
- regular files and file deletions only;
- symlink targets and symlink parent paths are rejected;
- path traversal / absolute changed paths are rejected.

Git status is read using NUL-delimited porcelain output with rename detection
disabled, preserving spaces safely and representing a move as delete + add.

## Recovery point

A recovery directory is created before Apply and must live outside the original
project.

Its manifest records:

- version;
- state;
- original root;
- original HEAD;
- original clean-status expectation;
- approved changed files;
- review content fingerprint;
- verifier-spec fingerprint;
- applied-worktree fingerprint after successful Apply.

Recovery states used by CP-07A:

- CREATED;
- APPLIED;
- ROLLED_BACK;
- NEEDS_ATTENTION.

The original Git HEAD is intentionally not changed by Apply, so that HEAD remains
the recovery authority for tracked content.

CP-07A does not create commits, branches, pushes, tags, stashes, or Git clean/reset
operations in the user project.

## Apply

Apply copies only reviewed regular-file content from sandbox to original, or
deletes the corresponding original file when the reviewed sandbox deletion is
approved.

Immediately after mutation XP requires:

- changed-path set exactly equals the approved review;
- git diff --check passes;
- at least one explicit verifier exists;
- every explicit verifier passes against the original project.

Verifier execution retains CP-06A protections, including side-effect detection.

If post-Apply verification succeeds:

- result = APPLIED;
- original HEAD remains unchanged;
- recovery manifest state = APPLIED;
- applied worktree fingerprint is stored.

The worktree remains intentionally uncommitted for human inspection.

## Automatic rollback

If Apply or post-Apply verification fails after mutation starts, XP attempts an
immediate rollback to the unchanged expected HEAD.

Rollback examines the current changed paths:

- tracked paths are restored from expected HEAD;
- untracked paths created by Apply/verifier are removed individually;
- empty directories created by the bounded Apply may be removed;
- no broad git clean is used.

After rollback, the original must be clean.

A dedicated test proves that a verifier-created side-effect file is also removed
during automatic rollback.

If automatic rollback itself cannot restore safety, the result becomes
NEEDS_ATTENTION instead of pretending success.

## Manual rollback

After a successful Apply, manual rollback requires:

- recovery manifest state = APPLIED;
- original HEAD still equals recovery HEAD;
- current worktree fingerprint exactly equals the fingerprint saved immediately
  after Apply.

If a user edits the project after Apply, manual rollback refuses rather than
overwriting the newer user change.

On a valid rollback, original tracked content is restored from HEAD, new
untracked Apply files are removed, and recovery state becomes ROLLED_BACK.

## Discard

Discard rechecks:

- clean expected original baseline;
- current sandbox review freshness.

It then returns DISCARDED without creating a recovery point and without mutating
the original project.

## TDD and regression evidence

CP-07A began with expected RED failures:

- missing xp_next.apply_control;
- runtime phase still CP-06A.

New tests cover:

- successful Apply;
- recovery creation;
- no automatic commit;
- modified/new/deleted file application;
- stale dirty original rejection;
- changed original HEAD rejection;
- stale sandbox rejection;
- truncated review rejection;
- Discard preserving original;
- post-Apply verifier failure rollback;
- verifier side-effect cleanup during rollback;
- successful manual rollback;
- manual rollback refusal after a later user edit;
- NUL-delimited changed paths with spaces and move-as-delete/add semantics.

Final deterministic suite:

- 92 tests;
- all PASS.

During development, one support job failed only because git diff --check detected
an extra blank line at EOF; that formatting issue was fixed.

A later new rollback-side-effect test initially failed because the test verifier
string itself had an escaping error. The verifier fixture was corrected and the
full suite then passed. No failed test was accepted as success.

A pre-existing non-failing SQLite ResourceWarning can still appear in an older
planner-service test. It does not affect CP-07A test results.

## Fixture acceptance

An independent fixture acceptance proved:

- reviewed Apply = PASS;
- original HEAD unchanged;
- recovery manifest created before/for Apply;
- post-Apply verifier = PASS;
- manual rollback = PASS;
- rollback restored a clean original;
- Discard = PASS;
- Discard left original unchanged.

No local AI or Hermes run was needed for CP-07A acceptance because this
checkpoint tests the deterministic post-review control plane.

## Safety boundaries retained

CP-07A:

- does not auto commit;
- does not auto push;
- does not deploy;
- does not migrate databases;
- does not use 9Router;
- does not use paid/cloud AI;
- does not silently change provider/model;
- does not apply to Segeran Jiwa;
- does not touch production databases;
- leaves XP+ 2.1.0 stable unchanged.

The filesystem recovery manifest is not yet persisted into the canonical SQLite
recovery_points table. That integration is intentionally deferred rather than
added without an end-to-end job-state transaction.

## Next allowed checkpoint

CP-08A — Zero-Cost Independence E2E.

One fresh fixture flow should prove the complete user path with paid/cloud AI
disabled:

goal
-> local context
-> local Qwen reasoning
-> bounded plan
-> isolated Hermes worker
-> sandbox verification
-> human review
-> explicit Apply
-> post-Apply verification
-> completed state

The E2E checkpoint should also wire operational job/recovery/activity state
without weakening the CP-07A guards.

It must remain fixture-only, with no Segeran Jiwa or production mutation.
