# XP Next — CP-00 Freeze Baseline

Status: SAFE CHECKPOINT
Date: 2026-09-20

## Purpose

Preserve XP+ 2.1.0 as the stable legacy/kernel reference before XP Next development starts.
This checkpoint does not modify XP+ 2.1.0 source code or the Segeran Jiwa production projects.

## Canonical XP+ 2.1.0 reference

- Stable release commit: 5cc52145c6d1cc6b435cac00bdbcf2f14370e23b
- Stable release branch: work/xp-plus-2.1.0-release
- Stable tag: v2.1.0
- Canonical tree: 946d95699de8c64b49d88ca1c9b5e2e48e740bda
- Active installed runtime: 2.1.0
- Previous runtime marker: 2.0.0-rc18.3

The stable release branch and v2.1.0 tag resolve to the same source tree.

## Important authority finding

origin/xp-engine is not used as the immutable XP+ 2.1.0 source reference.

At CP-00 audit time it had additional control-state and lease commits after the stable release and differed only in:

- leases/segeran-jiwa-pos-next.json
- state/xp-control-state.json

Therefore XP Next preservation authority is:

1. v2.1.0
2. work/xp-plus-2.1.0-release
3. exact commit 5cc52145c6d1cc6b435cac00bdbcf2f14370e23b

## Product decision

XP+ 2.1.0 is frozen as a legacy/kernel reference.

XP Next will be a fresh composition with selective reuse of proven modules. Normal XP Next workflow must not depend on ChatGPT or GPT handoff.

Locked direction:

- zero-cost first
- local-first
- provider-independent
- deterministic tools before AI
- local AI as the default zero-cost reasoning path
- Hermes or other agents are replaceable workers
- recovery before risky mutation
- verifier before declaring success
- explicit approval for meaningful mutation and high-risk operations
- no silent provider or model fallback
- no production deploy by default
- no destructive database operation by default
- simple user experience; technical detail lives in Developer Mode

## CP-00A acceptance

- XP+ 2.1.0 stable worktree was clean before this checkpoint.
- Stable source commit was not changed.
- Stable tag and tree were not changed.
- A separate XP Next planning worktree and branch were created.
- Only this XP Next baseline document is added on the planning branch.
- No Segeran Jiwa source was modified.
- No database migration or production deployment was performed.

## Next allowed work

CP-00B only:

- inventory reusable XP+ 2.1.0 modules;
- classify each as REUSE / ADAPT / REWRITE / DROP;
- identify legacy GPT-coupled paths that must not enter XP Next;
- no XP Next implementation code yet.

Do not start CP-01 until CP-00B is explicitly reviewed and accepted.
