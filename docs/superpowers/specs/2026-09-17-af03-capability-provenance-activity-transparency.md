# AF-03 Capability, Provenance & Activity Transparency — Design Spec

**Status:** FINAL LOCK
**Version:** 1.0
**Date:** 2026-09-17
**Project:** Expert Workstation XP+

## Purpose

AF-03 makes XP transparent about three separate things: capability availability, source/data provenance, and the observable actions actually performed for a job. XP must never present an unchecked or failed operation as successful, must never silently switch AI/provider, and must never expose hidden chain-of-thought.

## Locked Rules

1. Normal checks remain local/offline.
2. Live Check runs only after an explicit user request.
3. Live Check checks meaningful capabilities, not only connectivity, and records a timestamp.
4. Capability state uses explicit semantics: `AVAILABLE`, `NEEDS_ATTENTION`, `UNAVAILABLE`, `NOT_CHECKED`.
5. `NOT_CHECKED` is never rendered as available.
6. A capability that fails during real use is updated to `NEEDS_ATTENTION`; XP must not preserve a stale green state.
7. AI/provider fallback is never silent. Any alternative provider/model use must be explicit, visible, and represented in activity history.
8. Source/data provenance is distinct from AI/model processor and from the tool/route used to obtain or process it.
9. Internet-backed answers are visibly marked `LIVE`; answers that rely only on model knowledge are visibly marked `AI KNOWLEDGE`.
10. Each job has an Activity Trail containing only actions that actually occurred.
11. The Activity Trail records observable actions, sources, processors, routes/tools, timestamps, and outcomes, but never hidden chain-of-thought or scratchpad reasoning.
12. Each activity event has a simple status/result such as `COMPLETED`, `FAILED`, `NEEDS_ATTENTION`, plus objective metadata when available (source count, test count, last-check time, etc.).
13. Job history and Activity Trail remain readable after the job finishes.
14. There is no background Live Check, provider monitoring loop, or silent auto-refresh.
15. Anti-fake-success semantics are binding: `Unknown != Success`, `Not Checked != Available`, `Requested != Completed`, `Started != Completed`, `AI Generated != Live`, and `Fallback != Original Provider`.

## Conceptual Model

### Provenance

Every externally sourced or processed result can represent three independent dimensions:

- **Source** — where the data/fact originated, e.g. `project-local`, `file`, `git`, `github`, `live-web`, `database`, `user-input`, `ai-knowledge`.
- **Processor** — AI/model or non-AI processor that transformed/interpreted it, e.g. `Gemini`, `Qwen`, `OpenAI`, `local-model`, or `none`.
- **Via** — the mechanism used, e.g. `filesystem`, `git`, `github-api`, `web-search`, `http`, `tool`, `agent`, `test-runner`.

### Activity Event

The semantic minimum for an event is:

- `event_id`
- `job_id`
- `timestamp`
- `category`
- `action`
- `source`
- `processor`
- `via`
- `status`
- `result_summary`
- `metadata`

The implementation may use different internal names only if these semantics are preserved.

### Minimum Activity Categories

`LOCAL`, `PROJECT`, `FILE`, `GIT`, `GITHUB`, `LIVE_WEB`, `AI`, `TOOL`, `AGENT`, `TEST`, `USER`, `SYSTEM`.

Categories describe actions that actually happened; they are not a checklist that every job must contain.

## User-visible Semantics

A concise capability view may render:

- `✓ Tersedia`
- `⚠ Perlu perhatian`
- `✕ Tidak tersedia`
- `— Belum diperiksa`

A live result includes its actual last-check time. A previous successful check does not imply current availability.

A real internet-backed result is labeled `LIVE`. A model-only response is labeled `AI KNOWLEDGE`.

The user may open job history to answer questions such as "Tadi jawaban ini ambil dari mana?" using the persisted Activity Trail.

## Out of Scope

AF-03 does not add an automatic AI router, automatic best-model selection, 24-hour network monitoring, cloud telemetry, user analytics, chain-of-thought storage, provider auto-healing, or background monitoring service.

## Acceptance Criteria

AF-03 is complete only when tests prove all of the following:

1. Basic XP checks work without internet.
2. Live Check cannot run unless explicitly requested.
3. Live Check records a timestamp.
4. Unchecked capability state is not rendered as available.
5. Real-use capability failure produces `NEEDS_ATTENTION`.
6. No silent AI fallback occurs.
7. Source, processor, and via are represented separately.
8. `LIVE` and `AI KNOWLEDGE` are distinguishable.
9. Every instrumented job can own an Activity Trail.
10. The trail contains only explicitly recorded observable actions.
11. The trail never stores chain-of-thought.
12. Every event has a status/outcome.
13. Test events can record pass/fail counts.
14. Web events can record source counts.
15. Activity history remains readable after job completion.
16. No background Live Check runs.
17. Activity history records the actual AI/model used.
18. Failure cannot be rendered or persisted as success.

## Final Contract

XP must be able to show what it actually did, which source it used, which capability/tool route it used, which AI/model processed the data, and what the observable outcome was — without inventing activity, hiding failure, silently changing providers, or exposing hidden reasoning.
