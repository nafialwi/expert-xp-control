# AF-04 Verification Evidence

Date: 2026-09-18

## Identity

- Branch: `work/af04-zero-cost-usage`
- AF-04 implementation HEAD before evidence commit: `c1af5ca10fcb66e8f06a3a947f821feb7515e7aa`
- AF-03 merged base: `308f78f`
- Spec: `docs/superpowers/specs/2026-09-18-af04-zero-cost-model-usage-policy.md`
- Plan: `docs/superpowers/plans/2026-09-18-af04-zero-cost-model-usage-policy.md`

## AF-04 commit chain

```text
e499c6e docs(af04): add zero-cost model usage policy spec
77c9266 docs(af04): final lock zero-cost model usage policy
f3e9dba docs(af04): add implementation plan
8ef7724 feat(af04): add zero-cost policy contracts
45caecd feat(af04): persist job ai policy state
15ad795 feat(af04): enforce zero-cost policy before transport
20cbadb feat(af04): persist cost evidence and freshness
c02c231 feat(af04): capture objective ai usage
a42684d feat(af04): add task category and user feedback
aab8a91 feat(af04): add evidence-based model recommendations
258c8ad feat(af04): require explicit model switching
c1af5ca feat(af04): expose transparent ai usage views
```

## Verification results

- Dedicated AF-04: **Ran 79 tests in 2.760s — OK**
- AF-02 regression: **Ran 41 tests in 0.009s — OK**
- AF-03 regression: **Ran 36 tests in 0.672s — OK**
- Critical policy/safety tripwires: **Ran 6 tests in 0.027s — OK**
- Final full regression: **Ran 261 tests in 27.610s — OK, skipped=1**

## Zero-cost enforcement

The critical transport tripwires passed:

- a known `paid` route is blocked before transport execution;
- an `unknown` route without exact job-scoped approval is blocked before transport execution;
- exact job/route/model approval remains the authorization boundary for unknown-cost execution;
- no paid override exists in AF-04.

User-facing cost terms remain:

- `free` → **Gratis**
- `paid` → **Berbayar**
- `unknown` → **Biaya belum diketahui**

## Offline and explicit-live invariants

Plain `xp check` was executed during final verification and confirmed:

- `Mode: LOCAL/OFFLINE`;
- `Live Check: Belum diperiksa`;
- no `Mode: LIVE` marker.

The dedicated AF-03 tripwire also passed, proving plain checks do not build the Live Check service.

Static AF-04 inspection found:

- no non-transport network call surface in AF-04 modules;
- no background timer/polling/daemon loop surface;
- network code remains confined to the explicit OpenAI-compatible transport boundary.

## No silent fallback or automatic switch

The selected-route failure regression passed and did not execute an alternate route.

The production AF-04 static scan found no `fallback` surface.

Model switching requires explicit approval for each switch. The dedicated switch tripwires passed, including the local-only/no-network switch boundary.

## Usage, evidence, and recommendations

AF-04 keeps these distinctions visible:

- configured model vs provider-reported served model;
- configured cost state vs observed cost evidence;
- technical result vs user quality feedback;
- Activity Trail vs cross-job Usage History.

Recommendation evidence remains thresholded:

- 0–4 comparable jobs → initial recommendation only;
- history may support recommendations at 5+ comparable jobs;
- user-perceived quality claims require at least 3 feedback-bearing comparable jobs;
- no synthetic score, leaderboard, or automatic model selection is introduced;
- final choice remains with the user.

## Hidden-reasoning and persistence safety

Final schema inspection confirmed no persistence field named:

- `chain_of_thought`;
- `scratchpad`;
- `reasoning_content`;
- `hidden_reasoning`.

Textual occurrences in production are limited to deny-list/safety logic used to reject hidden-reasoning content.

Observable model handoff is limited to goal, files, decisions, results, errors, progress, and next action.

## Protected scope

Canonical SHA-256 values remained unchanged:

- `src/xp/adapters/generic.py` — `46265e421df168430b33429abe9f9ddd3db4c927d11ec7691bc9db7ac75ec4ed`
- `src/xp/executor.py` — `22a20b055b41ab1bfef67eb9fcbece537e281995928e396405ff2afcff756ffe`
- `src/xp/workflow.py` — `ff75df691debfca99c9a7245d36c7316d1b1f9c92de83c455109c1596bbdeaec`
- `src/xp/config.py` — `75d7236112b4c461d235a391afd9466a5ca724ed5783395c3272d3fe86206bb8`

`git diff 308f78f..c1af5ca10fcb66e8f06a3a947f821feb7515e7aa` for those four protected files was empty.

## Presentation and CLI

AF-04 exposes minimal local inspection surfaces:

- `xp ai-usage <job-id> [--expand]`
- `xp ai-recommend <category> [--expand]`

Compact output is the default. Expanded output exposes evidence and limitations.

Missing provider token counts render as **Tidak tersedia**, never as synthetic zero.

Recommendation readiness that has not been checked remains **Belum diperiksa**, not available.

## Scope boundary

AF-04 remains a zero-cost policy, observability, usage-history, recommendation, and explicit model-switching layer.

Real Qwen execution and autonomous multi-model orchestration remain outside AF-04 and are reserved for AF-05.

## Completion gate

All Task 10 verification gates passed before this evidence file was written:

- dedicated AF-04 tests passed;
- AF-02 regression passed;
- AF-03 regression passed;
- critical policy/safety tripwires passed;
- final full regression passed;
- plain check remained local/offline;
- no silent fallback was observed;
- no hidden background/live polling surface was found;
- hidden-reasoning persistence schema guard passed;
- protected files remained byte-identical to canonical hashes;
- pre-evidence worktree was clean.

AF-04 is therefore **FINAL VERIFIED** on this branch, pending the normal review/PR/merge workflow.
