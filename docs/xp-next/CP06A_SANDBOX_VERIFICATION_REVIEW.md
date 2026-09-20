# XP Next — CP-06A Sandbox Verification + Human Review Bundle

Status: SAFE CHECKPOINT
Date: 2026-09-21
Parent: 3c700d864d2cb9158aea057ee0829f075d56a8b1

## Purpose

Verify the changed isolated sandbox after worker execution and produce a bounded,
human-readable review package before any Apply capability exists.

CP-06A keeps the original project unchanged.

## Verification states

The review contract has three explicit states:

- PASS: structural safety checks and all configured verifiers passed.
- FAIL: a safety check failed, a verifier failed, or a verifier mutated the sandbox.
- UNVERIFIED: structural checks passed but no explicit verifier was configured.

UNVERIFIED is never silently promoted to PASS.

## ReviewBundle

The bundle records:

- verification status;
- summary;
- changed-file list;
- bounded textual diff;
- whether the diff was truncated;
- verifier results;
- apply_to_original_performed = false.

The same bundle can render human-readable review text suitable for a future PWA.

## Structural checks

Before running explicit verifiers, CP-06A requires:

- a Git-backed sandbox project;
- no Git remote in the sandbox;
- at least one changed file;
- Git diff check must not report errors.

If a sandbox has a remote, the review fails closed.

If there are no changes, the review fails rather than pretending there is
something ready to review.

## Bounded diff

Changed paths are captured from the sandbox Git status.

Tracked-file diffs are generated relative to sandbox HEAD.

Untracked-file diffs are rendered against /dev/null.

The combined diff is bounded by max_diff_chars. If the limit is exceeded, the
bundle marks diff_truncated = true and appends an explicit DIFF TRUNCATED marker.

The default bound is 12,000 characters.

## Explicit verifier contract

VerifierSpec contains:

- human-readable name;
- direct argv tuple;
- bounded timeout.

Verifier execution uses subprocess argv directly with shell disabled.

The verifier environment is sanitized:

- dedicated temporary HOME;
- dedicated temporary TMPDIR;
- no inherited arbitrary secrets;
- Python bytecode writing disabled;
- Git credential prompting disabled;
- external proxy values directed to a dead loopback proxy.

Obvious shell/network wrapper executables are rejected in CP-06A, including:

- sh
- bash
- zsh
- fish
- curl
- wget
- ssh
- scp
- rsync

Verifier specifications are trusted local configuration. They are not generated
from model text.

This remains best-effort process containment rather than a kernel-level jail.

## Verifier side-effect protection

Before each explicit verifier, XP records:

- sandbox content digest;
- changed-path set.

After the verifier it records them again.

If the verifier changes sandbox content or the changed-path set, the review
fails closed with a verifier-mutated-sandbox result.

A verifier is expected to verify, not edit.

## Human review

render_text() produces a concise review containing:

- status;
- summary;
- explicit notice that Apply to original was not performed;
- diff truncation state;
- changed files;
- verifier results;
- bounded diff.

No hidden chain-of-thought is included.

## TDD evidence

Tests were written before the module.

Expected RED state included:

- missing xp_next.sandbox_review;
- missing review_sandbox service function;
- runtime phase still CP-05A.

After implementation, the suite passed.

A hardening test was then added to reject common shell/network wrapper verifier
executables and verifier execution was made explicitly shell-free.

Final deterministic suite:

- 81 tests;
- all PASS.

A pre-existing non-failing Python ResourceWarning about an SQLite connection can
still appear in one older planner-service test. It does not change test result
or CP-06A behavior and is not treated as a hidden failure.

## Fixture acceptance

A fresh original fixture was created with:

- original.txt;
- a .env secret fixture;
- local Git baseline.

XP then:

1. created an isolated workspace;
2. confirmed .env was excluded;
3. added proof.txt only in the sandbox;
4. ran a trusted local proof-check verifier;
5. built the structured and human-readable review bundle;
6. checked the original fixture again.

Observed result:

- review status = PASS;
- changed files = proof.txt only;
- verifier status = PASS;
- diff_truncated = false;
- Apply to original = false;
- human review contained the changed file, verifier result, and bounded diff;
- original Git HEAD unchanged;
- original Git status unchanged;
- original content unchanged.

The post-hardening acceptance was repeated and passed.

## Safety boundaries retained

CP-06A:

- does not Apply changes to original source;
- does not implement Discard/Rollback yet;
- does not commit/push/deploy user projects;
- does not use 9Router;
- does not use paid/cloud AI;
- does not touch Segeran Jiwa;
- does not touch production databases;
- leaves XP+ 2.1.0 stable unchanged.

## Next allowed checkpoint

CP-07A — Apply / Discard / Rollback foundation.

Narrow scope:

- capture an original-project recovery point before Apply;
- verify original HEAD/status still match the expected baseline;
- Apply only the reviewed bounded sandbox change;
- rerun verifier against the original;
- rollback automatically if post-Apply verification fails;
- Discard must leave original untouched;
- no auto commit, push, deploy, or database migration;
- fixture only;
- commit, push, verify remote SHA, then stop.
