# Expert XP — Personal AI Foundation Roadmap

## Scope

Build the owner's personal Expert XP first.

Do not expand to a general public/universal distribution until the personal engine is stable and proven on real workflows.

## AF-00 — 9Router / Agent PoC

Status: DONE

Acceptance achieved:

- 9Router reachable
- Gemini reachable
- streaming works
- tool calling works
- Qwen Code works through 9Router
- real file editing works
- test execution works
- independent 2/2 test verification passes

## AF-01 — Durable Checkpoint

Status: IN PROGRESS

Goal:

Persist enough verified technical state that a different AI, new chat, new device or future session can continue without reconstructing the original conversation.

Deliverables:

- handoff
- PoC evidence
- source/runtime anchor
- architecture decisions
- roadmap
- no secrets

## AF-02 — XP AI Gateway

Goal:

Introduce an XP-owned AI abstraction.

Requirements:

- XP must not hard-code Gemini
- XP must not hard-code 9Router as mandatory
- provider/router adapters must be replaceable
- health/status interface must be defined
- agent runtime must be separable from model provider

Initial adapter:

- 9Router

Initial proven route:

- Qwen Code → 9Router → Gemini

## AF-03 — Health & Compatibility

Goal:

Turn the manual PoC setup into reproducible checks.

Requirements:

- detect Qwen version
- detect known `tts_notification` compatibility issue
- safely patch or report incompatibility
- detect 9Router
- verify `/v1/models`
- verify streaming
- verify tool calling
- provide one XP health-check result

## AF-04 — Zero-Cost & Usage Policy

Goal:

Prevent accidental paid usage and expose model consumption.

Requirements:

- paid route blocked by default
- unknown-cost route not automatically selected
- free-to-paid fallback blocked
- input/output/total tokens recorded when available
- latency and errors recorded
- one model per task by default
- local answers avoid LLM use

## AF-05 — XP Agent Dummy Integration

Goal:

XP itself initiates and supervises the previously proven coding-agent workflow.

Acceptance:

XP
→ agent
→ AI Gateway
→ 9Router
→ model
→ read/edit/test
→ XP verification
→ checkpoint

Must use a throwaway dummy project before any real application repository.

## AF-06 — Recovery & Device Independence

Goal:

A lost/replaced device must not destroy XP continuity.

Initial personal scope:

- Git remote as canonical source
- XP checkpoint
- recovery manifest
- export/import bundle
- secrets excluded
- path portability
- new-device restoration test

Android/Termux is the first supported environment.

Desktop portability remains architectural, not yet full production scope.

## AF-07 — Multi-AI Routing

Goal:

Test a small useful set of additional available routes.

Do NOT connect/use every model merely because 9Router lists it.

Initial target roles:

- fast/light model
- coding model
- stronger reasoning model
- zero-cost fallback

Evaluate:

- tool calling
- coding reliability
- latency
- context behavior
- stability
- cost eligibility

## AF-08 — Conversational XP

Goal:

Replace menu-driven daily operation with natural-language control while retaining CLI recovery.

Examples:

- `lanjutkan Next`
- `pekerjaan terakhir sampai mana?`
- `cek hasil terakhir lalu lanjutkan`
- `lanjut sampai human gate`
- `buat laporan progres`
- `brainstorming fitur baru`

XP must resolve intent against real XP state rather than forwarding raw text blindly to an AI.

## AF-09 — Real Project Pilot

Goal:

Use conversational/autonomous XP on one controlled real project.

Requirements:

- state-aware continuation
- Superpowers workflow
- source protections
- verification
- checkpointing
- human gates
- rollback/recovery

Only after AF-05 through AF-08 are sufficiently stable.

## AF-10 — PWA / Browser UX

Goal:

Provide the normal daily interface in browser/PWA for mobile and desktop.

Terminal remains:

- admin interface
- recovery interface
- debugging interface

PWA concepts include:

- conversational chat
- projects
- activity
- approvals
- AI route/status
- usage/tokens
- files/diffs
- recovery/settings

UI implementation is intentionally deferred until the engine and workflow semantics are stable.

## Deferred

Not current scope:

- public multi-user XP
- universal installer for everyone
- all AI providers
- all operating systems
- public plugin marketplace
- cloud-hosted XP control plane

These may be reconsidered after the personal XP build proves stable.
