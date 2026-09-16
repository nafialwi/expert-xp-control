# Expert XP — AI Foundation Handoff

## Checkpoint

- Milestone: AF-01 Durable Checkpoint
- Recorded: 2026-09-17
- Status AF-00: PASS
- Current AF-01 branch: `work/af01-durable-checkpoint`
- Control repository baseline: `d8bec19479f399638ef6d81f596b5155e646afba`

## Active XP Runtime

- Product: Expert Workstation XP+
- Active version: `2.1.0`
- Executable: `xp`
- Active runtime path: `~/.expert-workstation/versions/2.1.0`
- Product metadata:
  - `PRODUCT_NAME = "XP+"`
  - `CLI_NAME = "xp"`

### Canonical Source Anchor

The installed XP+ 2.1.0 Python source was compared against the Git worktree at:

`~/.expert-workstation/worktrees/xp-plus`

Comparison excluded runtime-only `__pycache__` and `*.pyc`.

Result:

`diff -qr ... -> EXIT=0`

Therefore the active 2.1.0 source is anchored to:

- Commit: `36a89eea364606d565759d5fa9bf59196003f9aa`
- Branch at verification time: `work/xp-plus-v1`
- Commit date: `2026-09-13T13:55:43+07:00`
- Commit subject: `fix(xp+): restore lifecycle health authority`
- Remote branch containing commit: `origin/xp-engine`

This Git commit is the source-of-truth anchor for the active XP+ 2.1.0 engine.

The older `xp-source-bundle.txt` in the control repository contains XP `2.0.0-rc6` and MUST NOT be treated as the active 2.1.0 engine source.

## AI Foundation PoC

The following path was tested successfully:

Qwen Code
→ OpenAI-compatible API
→ 9Router
→ Gemini
→ tool calls
→ filesystem operations
→ test execution

### Components Verified

- Qwen Code Termux: `0.22.2-termux`
- 9Router observed version: `0.5.75`
- 9Router local base URL: `http://127.0.0.1:20128`
- OpenAI-compatible route: `/v1`
- Working model during PoC: `gemini/gemini-3.5-flash-lite`

The API credential is a LOCAL SECRET and is intentionally not stored in this repository.

## Qwen Compatibility Finding

Initial Qwen requests reached the OpenAI-compatible endpoint but Gemini rejected the tool schema.

Root cause was the `tts_notification` tool constructor passing:

`TTS_SCHEMA.properties`

instead of the complete JSON schema:

`TTS_SCHEMA`

Observed installed file:

`@mmmbuto/qwen-code-termux/chunks/tts-notification-KGLYKHAM.js`

Minimal local compatibility patch:

- Before: `TTS_SCHEMA.properties`
- After: `TTS_SCHEMA`

After the patch, the previously captured Qwen payload succeeded through 9Router/Gemini.

Important: this is currently a local node_modules compatibility patch and may be overwritten by Qwen reinstall/update. AF-02/AF-03 must make the detection/fix reproducible rather than relying on manual editing.

## End-to-End Verification

A throwaway project was created at:

`~/9router-agent-test`

Initial implementation:

`return harga - jumlah;`

Initial independent test result:

- tests: 2
- pass: 0
- fail: 2

Qwen Code was then instructed to:

1. read `test.mjs`
2. read `calc.mjs`
3. identify root cause
4. modify only `calc.mjs`
5. run `node --test test.mjs`

Qwen changed the implementation to:

`return harga * jumlah;`

Independent verification performed outside Qwen:

- tests: 2
- pass: 2
- fail: 0

Therefore the coding-agent PoC is considered PASS.

## Token / Usage Baseline

A trivial one-turn Qwen request through the tested route reported approximately:

- input tokens: 15,737
- output tokens: 8
- total tokens: 15,745

This demonstrates that Qwen's agent/system/tool context can be much larger than the user's visible prompt.

Design consequence:

- XP MUST NOT invoke a full coding agent for questions that can be answered locally.
- Local state queries should use zero model tokens where possible.
- AI should be invoked on demand.
- One model per task is the default.
- Multi-model review must not be automatic.

## Architecture Decisions Locked for Current Personal Build

Current priority is XP for the owner/user first, not a public universal release.

XP core must remain modular:

- XP owns project state, safety, workflow, recovery and policy.
- Superpowers owns development methodology.
- Coding agent is replaceable.
- 9Router is an adapter/router, not a mandatory XP dependency.
- AI model/provider is replaceable.
- GitHub is preferred canonical continuity storage but must not become an XP runtime dependency.
- PWA/UI is deferred until the engine is stable.

Target AI structure:

XP
→ XP AI Gateway
→ agent runtime
→ router/direct adapter
→ model

Initial proven route:

XP
→ Qwen Code
→ 9Router
→ Gemini

## Zero-Cost Requirement

The personal XP build is zero-cost-first.

Required policy direction:

- paid API route: BLOCK by default
- free route: ALLOW
- unknown-cost route: do not auto-use
- free-to-paid fallback: BLOCK
- single-model execution: default
- explicit user approval required before any potentially paid route

Connected models do not imply model usage. Only executed requests consume model usage/tokens.

## Recovery / Continuity Principle

AI memory or chat history MUST NOT be the canonical project state.

Continuity order:

1. Git source / remote
2. XP checkpoint and handoff
3. portable recovery metadata
4. AI memory only as convenience

A replacement AI should be able to continue using this repository and this handoff without reading the original ChatGPT conversation.

## Resume Instruction for a New AI

Read, in order:

1. `docs/ai-foundation/AF-01-HANDOFF.md`
2. `docs/ai-foundation/AF-00-POC-EVIDENCE.md`
3. `docs/ai-foundation/AI-ROADMAP.md`

Then verify the current Git HEAD and active XP runtime before making changes.

Do not repeat AF-00 experiments unless verification shows the baseline is no longer valid.

Next milestone after AF-01 is AF-02: XP AI Gateway.
