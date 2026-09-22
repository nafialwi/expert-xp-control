# XP Next — CP-08H Human-Friendly Work Flow Checkpoint

**Date:** 2026-09-22T17:32:50+07:00
**Branch:** `planning/xp-next-bootstrap`
**Base CP-08G:** `7c10b9f0283ac368adcf9a6fbfd36f74f87e7a38`

## Outcome

CP-08H adds one human-facing `xp-next work` flow over the already locked
local project context, worker selection, isolated execution, verifier review,
and guarded Apply/Discard controls.

The interactive path is:

`project -> goal -> verifier preflight -> worker recommendation -> explicit worker confirmation -> explicit sandbox approval -> isolated execution -> verifier/review -> Apply or Discard -> post-Apply verification`.

## Safety contract

- local-first; no mandatory ChatGPT/paid API/9Router dependency;
- no silent worker fallback;
- Git project must be clean before work begins;
- only a canonical `npm run verify` is auto-discovered; otherwise an explicit verifier is required;
- verifier remains sandboxed by the existing CP-06A controls;
- Apply still requires a PASS, non-truncated, fresh review fingerprint;
- Apply does not commit, push, deploy, or run production database migrations;
- this checkpoint build did not touch Segeran Jiwa source or any production database.

## TDD evidence

- RED gate: expected CP-08H tests failed before implementation;
- targeted CP-08H regression: **18/18 PASS**;
- full XP Next regression: **142/142 PASS**;
- `git diff --check`: PASS;
- Python compile gate for changed Python surfaces: PASS.

## Files

- `next/src/xp_next/work_flow.py` — clean-source/project/verifier preparation;
- `next/src/xp_next/cli.py` — human-friendly `work` command and approvals;
- `next/src/xp_next/service.py` — phase advanced to CP-08H;
- `next/tests/test_work_flow.py` — preflight/verifier safety coverage;
- `next/tests/test_cli_work.py` — one-command Apply/Discard integration coverage;
- existing status tests updated to CP-08H;
- `next/README.md` updated for the CP-08H surface.

## Deliberate boundary

The installed public command remains `xp-next work` on this planning branch.
Replacing/cutting over the existing `xp` launcher is not part of CP-08H and
must remain a separate explicit release/cutover gate.
