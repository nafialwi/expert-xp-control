# AF-04 — Zero-Cost + Model Usage Policy

**Spec Version:** 1.0
**Date:** 2026-09-18
**Status:** REVIEW CANDIDATE
**Baseline:** `work/xp-plus-v1 @ 308f78f`
**Depends On:** AF-02 AI Gateway, AF-03 Capability/Provenance/Activity Transparency

---

## 1. Purpose

AF-04 adds the policy layer that controls which AI routes XP may use, how cost status is interpreted, how AI use is observed, how model changes are approved, and how XP may recommend models from real usage history.

Primary policy:

> XP must remain zero-cost. Routes known to require payment must not be used.

Real Qwen/agent runtime integration remains outside AF-04.

## 2. Locked principles

1. Zero-cost is mandatory.
2. Known paid routes are hard-blocked.
3. Unknown cost is not treated as free.
4. Unknown cost may be approved only for the current job/route/model.
5. XP never silently switches model/provider/route.
6. XP may recommend; the user decides.
7. Missing information stays missing; XP does not invent values.
8. Technical success is separate from user satisfaction.
9. Live cost verification runs only after explicit user action.
10. Activity history contains observable actions, never hidden reasoning.
11. AF-02/AF-03 contracts remain authoritative.

## 3. Cost terminology

Internal values remain `free`, `paid`, `unknown`.

User-facing labels:

- `free` → **Gratis**
- `paid` → **Berbayar**
- `unknown` → **Biaya belum diketahui**

"Gratis" means no AI/provider usage charge is currently known for the route. It does not claim electricity, hardware, or connectivity are costless.

Internal policy decisions may use `ALLOW`, `BLOCK`, and `REQUIRE_APPROVAL`, while UI uses **Diizinkan**, **Diblokir**, and **Perlu persetujuan**.

## 4. Architectural boundary

Policy enforcement lives between route selection and transport execution:

```text
AIRequest
   ↓
Route selection
   ↓
Zero-Cost / Model Policy
   ├─ free    → ALLOW
   ├─ paid    → BLOCK
   └─ unknown → REQUIRE_APPROVAL
   ↓
AI transport
   ↓
AIResponse
   ↓
Observation + Usage History
```

CLI is not a security boundary. Transports do not decide cost policy.

## 5. Provider-neutral components

AF-04 should introduce small units under `src/xp/ai/`:

- **ZeroCostPolicy** — evaluates effective cost, approval, and active model state; performs no provider HTTP.
- **PolicyDecision** — decision, reason, route, cost state, and approval requirement.
- **JobAIState** — job id, active route/model, approved unknown-cost route/model, switch history, completion state; survives resume and expires job approvals at completion.
- **CostEvidence** — observed cost state, timestamp, source/evidence, local/online classification.
- **UsageHistory** — sanitized cross-job observations for recommendations; never a hidden-reasoning store.

Activity Trail remains per-job audit; Usage History is cross-job experience.

## 6. Cost policy

### Free
A route with effective status `free` may execute.

### Paid
A route with effective status `paid` must be blocked before transport execution. There is no "use anyway" override.

### Unknown
A route with effective status `unknown` must not execute automatically. UI should offer:

```text
Status biaya: Biaya belum diketahui

[Periksa status biaya]
[Saya tahu ini gratis — gunakan untuk pekerjaan ini]
[Batal]
```

Approval is scoped to current job + route + model, survives resume of the unfinished job, does not change global configuration, expires at job completion, and is recorded observably. Activity Trail is evidence, not the authorization store.

## 7. Declared vs observed cost

AF-04 separates configured cost state from live/observed cost evidence.

```text
Status konfigurasi : Biaya belum diketahui
Hasil Live Check   : Gratis
Dicek              : 2026-09-18
Sumber             : provider documentation
```

Observed evidence never silently rewrites persistent configuration. Persistent changes require explicit approval.

## 8. Live cost verification

Normal operation remains local/offline. XP does not poll prices, refresh on startup, run background checks, or silently access the internet for cost refresh.

Live verification happens only after explicit user action. If no trusted verifier/source is available, XP says verification is unavailable rather than guessing.

A live result of `paid` blocks the current route immediately, even before any persistent classification update.

## 9. Freshness

Online cost evidence is considered stale after **30 days**.

A previously verified-free online route remains usable when stale, but XP shows **Status perlu diperbarui**. No automatic refresh occurs.

Explicitly classified local AI does not need price-evidence expiry. XP must not infer "local AI" merely from localhost/loopback because a local proxy may call an online provider.

## 10. Model selection and switching

XP may recommend a model; the user remains the decision-maker.

A job has exactly one active model at a time. A job may use more than one model only through explicit switching.

Every switch records previous route/model, new route/model, timestamp, user approval, and optional reason.

XP never silently retries on another AI after failure.

## 11. Model handoff

After an explicit model switch, XP may hand off observable job state: goal, files/resources, explicit decisions, produced outputs, observed errors, current progress, and next known action.

Handoff must never contain hidden chain-of-thought, private scratchpad, internal reasoning content, or fabricated rationale.

## 12. Configured model vs served model

XP stores both the configured/requested model and provider-reported/served model.

A meaningful mismatch becomes **Perlu perhatian**. The completed response remains in history, but XP does not silently continue subsequent requests under an unexplained mismatch.

## 13. Usage observation

When available, AF-04 records:

- job id;
- route/provider/transport;
- configured model;
- served model;
- task category;
- effective cost state;
- latency;
- input/output/total tokens;
- completion/error status;
- optional user feedback.

Provider-reported token usage is retained. Missing token data remains unavailable, never converted to zero. Latency may be measured locally with a monotonic timer. Latency alone is not quality.

## 14. Task categories

Initial categories:

- Coding / Debugging
- Audit / Review
- Analisis / Reasoning
- Riset / Web
- Dokumen / Writing
- Data / Spreadsheet
- Desain / Visual
- General

XP may auto-detect a category, but it is always visible and user-correctable. Corrections are observable and do not silently rewrite history.

## 15. User feedback

Feedback is optional and is primarily requested when a job completes or when the user switches model.

States:

- **Bagus**
- **Cukup**
- **Kurang sesuai**
- **Belum dinilai**

Optional negative reasons may include kurang akurat, kurang lengkap, salah memahami tugas, terlalu lambat, masalah tool, and lainnya.

Technical success never creates positive user feedback automatically.

## 16. Recommendation evidence

AF-04 does not create synthetic model scores or leaderboards.

Recommendations show observable evidence such as sample size, technical success, feedback, and latency.

For one model and one task category:

- **0–4 comparable jobs:** XP may give an initial recommendation based on known capabilities, cost, readiness, and tool support, labeled **Rekomendasi awal — belum cukup riwayat penggunaan XP.**
- **5+ comparable jobs:** usage history may support history-based recommendation.
- **Feedback quality claims:** require at least **3 feedback-bearing comparable jobs**.

Unequal sample sizes must be shown and not presented as equally strong evidence.

## 17. Recommendation safety

Recommendations may consider zero-cost eligibility, category, declared capabilities, readiness, tool compatibility, technical success, user feedback, and latency.

XP must not silently execute a recommendation, invent history, treat missing evidence as success, or treat faster latency as inherently better output quality.

## 18. Compact + Expand presentation

Default presentation stays compact, with expandable technical detail.

Compact example:

```text
AI
Gemini 3.5 Flash Lite

✓ Selesai
Gratis
14,2 detik
Hasil: Bagus

[▼ Lihat detail]
```

Expanded detail may include category, provider/route, configured and served model, token usage, latency, cost evidence and freshness, feedback, provenance, recommendation evidence, and model-switch history.

## 19. Activity Trail integration

AF-03 Activity Trail remains authoritative for observable per-job events. AF-04 should record policy allow/block, unknown-cost approval, live cost check requested/completed/failed, model switch, model mismatch, category correction, feedback, and AI completion/error.

Hidden reasoning is never recorded.

## 20. Persistence, security, privacy

Job AI policy state survives normal restart/resume for unfinished jobs. Usage history persists locally by default.

Persistent AF-04 state must be sanitized and exclude API keys, bearer tokens, raw authorization headers, secret environment values, hidden chain-of-thought, and private scratchpad content.

No automatic upload or provider synchronization is introduced.

## 21. Error semantics

Mandatory distinctions:

```text
Unknown cost          != Free
Missing tokens        != Zero tokens
Started request       != Completed request
AI generated          != Live verified
Fallback              != Original provider
Technical success     != User satisfaction
Old free verification != Paid
Configured model      != Served model
Recommendation        != User decision
```

XP surfaces uncertainty rather than manufacturing certainty.

## 22. Protected scope

AF-04 must not redesign or unnecessarily modify:

- `src/xp/adapters/generic.py`
- `src/xp/executor.py`
- `src/xp/workflow.py`
- `src/xp/config.py`

It preserves protocol v1, package execution semantics, GenericToolchain boundaries, project config semantics, AF-02 no automatic fallback, and AF-03 capability/activity/provenance semantics.

Any need to modify protected scope reopens design review.

## 23. Expected implementation area

AF-04 should primarily affect:

```text
src/xp/ai/
tests/
docs/superpowers/
```

Small supporting path/state changes are allowed only when needed for clean persistence boundaries. Unrelated refactoring is out of scope.

## 24. Out of scope

AF-04 does not implement full Qwen runtime integration, autonomous multi-model orchestration, paid-budget spending, automatic pricing polling, synthetic benchmark scores, cloud usage-history sync, hidden fallback, model racing, provider account management, or universal pricing scraping.

## 25. Acceptance criteria

AF-04 is not complete until tests prove at minimum:

1. Paid route never reaches transport.
2. Paid route cannot be overridden.
3. Unknown route never reaches transport without job approval.
4. Unknown approval is job/route/model scoped.
5. Unknown approval survives unfinished-job resume.
6. Unknown approval expires at job completion.
7. Free route may execute.
8. No automatic model switch exists.
9. Explicit model switch is observable.
10. Model handoff excludes hidden reasoning.
11. Configured and served models are stored separately.
12. Material served-model mismatch becomes Needs Attention.
13. Provider token usage is retained when present.
14. Missing token usage remains unavailable, not zero.
15. Latency is measured objectively.
16. Technical completion does not create positive feedback.
17. Feedback remains optional.
18. Task category is visible and correctable.
19. Category correction is observable.
20. Fewer than 5 comparable jobs cannot produce historical-confidence claims.
21. Five or more comparable jobs may support history-based recommendation.
22. Feedback-based quality claims require at least 3 feedback-bearing jobs.
23. Recommendation evidence exposes sample size.
24. Unequal sample sizes are not presented as equally strong evidence.
25. Live cost verification never runs automatically.
26. Live cost evidence remains separate from declared configuration.
27. Persistent cost-class change requires explicit approval.
28. Live verification showing paid blocks the current route.
29. Online free evidence older than 30 days is stale but still usable.
30. Stale cost evidence never triggers automatic network refresh.
31. Activity Trail remains free of hidden reasoning.
32. Usage history persists locally.
33. Usage history excludes secrets.
34. Protected files remain unchanged.
35. AF-02 regression passes.
36. AF-03 regression passes.
37. Full test suite passes.

## 26. Implementation strategy

Implementation follows TDD in this order:

1. canonical policy contracts;
2. zero-cost enforcement before transport;
3. job-scoped approval persistence;
4. observable model switching;
5. objective usage capture;
6. cost evidence and freshness;
7. task classification + feedback;
8. usage-history aggregation;
9. recommendation evidence rules;
10. compact/expanded CLI presentation;
11. regression + protected-scope verification.

Detailed file-by-file work belongs in the separate AF-04 Implementation Plan after this spec is reviewed and locked.

## 27. Completion definition

AF-04 is complete only when the spec is FINAL LOCK, implementation follows an approved TDD plan, dedicated AF-04 tests pass, AF-02 and AF-03 regressions pass, the complete suite passes, protected scope remains intact, no silent fallback exists, no automatic paid execution is possible, final evidence is recorded, and the feature is reviewed and merged through the normal PR process.
