# XP+ Blueprint v1.0 — Review Candidate

**Status:** FINAL LOCK — APPROVED 2026-09-13  
**Date:** 2026-09-13  
**Product name:** XP+  
**CLI command:** `xp`  
**Baseline engine:** XP `2.0.0-rc18.3`  
**Target first XP+ engine line:** `2.1.x`  
**Primary platform:** Android + Termux/X11  
**Design principle:** backward-compatible evolution, not rewrite

---

## 1. Purpose

XP+ is the next evolution of Expert Workstation (XP): a local-first, AI-portable,
multi-project engineering control plane that lets external AIs such as GPT, Qwen,
Claude, or another coding assistant propose declarative changes while XP remains
the execution, verification, recovery, checkpoint, and safety authority.

XP+ must improve the parts of XP that currently create avoidable friction:

- spec/documentation drift,
- incomplete project readiness profiles,
- oversized handoff bundles,
- unsafe/under-verified engine upgrades,
- weak separation between project capability discovery and business-specific logic,
- inconsistent onboarding experience,
- insufficient compatibility testing across different project types.

XP+ must preserve the parts that already work well:

- project registry,
- `.xp/` project metadata,
- package fingerprint validation,
- protected-branch enforcement,
- scoped package operations,
- backup + rollback,
- source verification,
- database approval gates,
- remote safepoints,
- remote lease protection,
- incident/remediation flow,
- human QA,
- Final Lock,
- checkpoint evidence and source archive,
- AI handoff portability.

---

## 2. Compatibility Contract — FINAL LOCK

This contract is mandatory for XP+ v1.

### 2.1 Stable external identity

| Surface | XP+ rule |
|---|---|
| Product display name | `XP+` |
| CLI | remains `xp` |
| Project metadata directory | remains `.xp/` |
| Package prefix | remains `XP_PKG_*` |
| Registry identity | existing `project_id` values remain unchanged |
| Existing work branches | remain valid |
| Existing control repo | remains valid |
| Existing checkpoint directories | remain valid |

### 2.2 Version compatibility

XP+ v1 must continue to natively support:

- `profile_version: 1`
- `state_version: 1`
- `protocol_version: 1`

No forced migration is allowed merely because the engine becomes XP+.

A future schema version may exist, but XP+ v1 must not require one.

### 2.3 Existing project guarantee

Existing projects such as:

- `segeran-jiwa-pos-legacy`
- `segeran-jiwa-pos-next`

must remain openable and operable without project conversion.

If a new XP+ capability requires new project metadata, that capability must degrade
gracefully and offer an explicit profile upgrade path. It must not make the project
unusable.

### 2.4 Existing run/checkpoint guarantee

XP+ must preserve readability of:

- existing run state,
- incident state,
- remediation context,
- existing locked checkpoints,
- source archives,
- SHA256 evidence,
- current registry and control state.

---

## 3. Evidence From Current Projects

### 3.1 Segeran Jiwa POS Legacy

Legacy demonstrates the failure mode XP+ must prevent:

- project is onboarded,
- profile is valid,
- but `runtimes` is empty,
- `source_verify` is empty,
- database/deployment adapters are absent,
- project can therefore appear registered while canonical verification is not configured.

The current engine treats an empty `source_verify` list as verification CLEAR with
the message that no source verification steps were declared.

**XP+ consequence:** onboarding/readiness must distinguish “registered” from “ready”.

### 3.2 Segeran Jiwa POS Next

Next demonstrates the capabilities XP+ must preserve:

- `profile_version: 1`,
- source adapter `git`,
- runtimes `node` and `python`,
- verify adapter `npm-script`,
- PostgreSQL database adapter,
- canonical `npm run verify`,
- required commands `git`, `python`, `node`, `npm`,
- protected branches,
- remote safepoint,
- known warning policy,
- database migration approval,
- SQL regression testing,
- human QA,
- Final Lock,
- locked remote checkpoints.

Next already has successful XP checkpoints, including a locked remote run with
checkpoint report, source archive, remote safepoint, human QA CLEAR, and released
remote lease.

**XP+ consequence:** new architecture must preserve this exact workflow before adding
new features.

---

## 4. Product Principles

### P1 — XP+ controls execution; AI proposes intent

AI may analyze, design, and produce a declarative spec.

XP+ remains responsible for:

- validating project identity,
- validating source state,
- validating package scope,
- applying changes,
- running verification,
- managing database approvals,
- creating remote safepoints,
- enforcing QA,
- recording checkpoints,
- recovery and remediation state.

### P2 — Evidence before assertion

XP+ must never call a project “safe”, “verified”, “locked”, or “ready” without a
machine-observable basis.

### P3 — No business hardcoding

XP+ must not know what “shift”, “cup”, “cashier”, “finance”, or other domain-specific
business terms mean.

It should only know capabilities and policies such as:

- source adapter,
- runtime,
- verification command,
- database adapter,
- deployment adapter,
- package scope,
- branch policy,
- QA requirements.

### P4 — Local-first, remote-protected

Local work should remain possible even with intermittent connectivity, but remote
lease/safepoint state must continue to protect against multi-writer conflicts.

### P5 — Safe-by-default upgrade

The XP+ engine itself must be upgraded with stronger guarantees than ordinary project
source changes.

### P6 — Cross-AI portability

No external AI should need private chat memory to continue a project.

---

## 5. XP+ Architecture

XP+ keeps the current engine structure conceptually but formalizes nine subsystems.

### 5.1 Core State

Responsibilities:

- run state,
- project registry,
- journal,
- locks,
- workflow transitions,
- configuration,
- control-repo state.

Compatibility requirement:

- existing state v1 remains readable.

### 5.2 Source Control

Responsibilities:

- Git state,
- fingerprint,
- branch protection,
- ahead/behind/diverged detection,
- commit/push,
- remote safepoint.

No change to the principle that work packages must not run on protected branches.

### 5.3 Project Capability Model

Capabilities become explicit and composable.

Initial built-in capability families:

- Git
- Node
- Python
- PostgreSQL

Future optional capabilities may include:

- Firebase diagnostics
- Supabase CLI
- Cloudflare deployment
- generic command runner with allow-list
- additional database adapters

A project profile chooses capabilities; XP+ does not infer business behavior from them.

### 5.4 Change Control

Responsibilities:

- machine-readable spec schema,
- package creation,
- package validation,
- checksums,
- allowed path enforcement,
- apply/replace/delete/patch operations,
- source backup,
- rollback.

### 5.5 Verification

Responsibilities:

- canonical source verification,
- warning classification,
- database tests,
- final verification,
- readiness assertions.

### 5.6 Recovery

Responsibilities:

- interruption inspection,
- safe retry classification,
- critical-operation escalation,
- incident generation,
- remediation matching,
- remote lease recovery/takeover.

### 5.7 Evidence & Final Lock

Responsibilities:

- checkpoint report,
- checkpoint state,
- source archive,
- SHA256 sums,
- QA evidence,
- commit identity,
- lock status.

### 5.8 AI Interface

Responsibilities:

- handshake,
- schema export,
- compact bundle,
- deep bundle,
- incident bundle,
- cross-AI instructions.

### 5.9 Engine Lifecycle

Responsibilities:

- install,
- candidate validation,
- side-by-side version storage,
- atomic activation,
- health check,
- automatic rollback,
- stable release promotion.

---

## 6. Canonical Spec & Schema

### 6.1 Problem

Current historical documentation/examples can drift from the implementation.
The actual rc18.3 builder consumes keys such as `type` and `human_qa`.

XP+ must remove documentation drift by making the engine schema authoritative.

### 6.2 New commands

XP+ v1 should add:

```bash
xp schema
xp schema work
xp schema remediation
xp schema project-profile
```

The output should be generated from one canonical schema definition used by:

- `pkg-build`,
- validation,
- `xp handshake`,
- documentation,
- tests.

### 6.3 Protocol v1 compatibility

Existing protocol v1 remains accepted.

XP+ v1 should not require a protocol bump unless an incompatible package feature is
truly unavoidable.

### 6.4 Spec validation before package build

`xp pkg-build` should provide specific errors such as:

- invalid field name,
- unsupported operation,
- missing `allowed_paths`,
- operation outside scope,
- missing `content`,
- invalid remediation state,
- unknown project.

Errors should include the canonical field name expected by XP+.

---

## 7. Project Doctor & Smart Onboarding

### 7.1 Project states

XP+ distinguishes:

```text
UNPROFILED
REGISTERED
PROFILE_INCOMPLETE
WORK_READY
WORKING
HUMAN_QA
READY_TO_LOCK
LOCKED
RECOVERY_REQUIRED
```

These are user-facing readiness categories, not replacements for internal run stages.

### 7.2 `xp project audit`

Add:

```bash
xp project audit <project-id-or-path>
```

It should report:

- Git repo detected,
- branch state,
- `.xp/` profile validity,
- runtime candidates,
- required command availability,
- verify configuration,
- database adapter readiness,
- deployment status,
- remote state,
- checkpoint continuity,
- active run/incident,
- readiness result.

Example:

```text
PROJECT READINESS

Git repository        CLEAR
Node detected         CLEAR
npm detected          CLEAR
Verify script found   CLEAR
Canonical verify      MISSING
Database adapter      NOT REQUIRED
Deployment            DISABLED

RESULT: PROFILE_INCOMPLETE
```

### 7.3 Smart onboarding

Existing-repo onboarding should:

1. inspect the repo,
2. discover candidate runtimes,
3. discover candidate verify scripts,
4. detect database markers,
5. propose a project profile,
6. show the proposal,
7. require user approval,
8. install `.xp/`,
9. run readiness audit,
10. only report WORK_READY when canonical verification is actually configured.

### 7.4 No silent policy invention

XP+ may recommend a verify script but must not silently choose one when multiple
equally plausible scripts exist.

---

## 8. AI Bundle v2

### 8.1 Default compact bundle

`xp bundle --repo <path>` should become compact.

Include:

- XP+ version,
- project identity,
- profile,
- policies,
- compatibility,
- Git state,
- current run,
- latest checkpoint,
- relevant roadmap snapshot,
- package schema summary,
- explicit instructions to the AI.

Do not include the full engine source by default.

### 8.2 Deep bundle

Add:

```bash
xp bundle --repo <path> --deep
```

Use for:

- XP engine debugging,
- compatibility audit,
- recovery audit,
- AI migration when source internals are required.

### 8.3 Optional focused context

Future-safe design:

```bash
xp bundle --repo <path> --paths src/foo.js tests/foo.test.js
```

This is useful but not required for the first XP+ stable release.

---

## 9. Engine Upgrade Safety

### 9.1 Current risk

The current upgrade flow fetches/pulls the engine branch, copies a new version into
the versions directory, and switches `active-version`.

XP+ must strengthen this.

### 9.2 XP+ candidate upgrade flow

```text
FETCH CANDIDATE
→ VALIDATE VERSION
→ INSTALL SIDE-BY-SIDE
→ SELF-TEST CANDIDATE
→ RUN COMPATIBILITY FIXTURES
→ CHECK EXISTING REGISTRY/STATE READABILITY
→ ATOMIC ACTIVE-VERSION SWITCH
→ POST-ACTIVATION HEALTH CHECK
→ SUCCESS
```

Failure before activation:

- active engine remains unchanged.

Failure after activation:

- restore `previous-version`,
- mark candidate failed,
- keep incident/evidence,
- do not alter project source.

### 9.3 Required engine metadata

XP+ engine installation should track:

- active version,
- previous version,
- install timestamp,
- candidate status,
- health-check result.

### 9.4 No project mutation during engine upgrade

Engine upgrade is separate from project package execution.

---

## 10. Adapter Model

### 10.1 Built-in adapters

XP+ v1 retains:

- Git,
- Node,
- Python,
- PostgreSQL.

### 10.2 Adapter contract

Every adapter must expose:

- stable capability names,
- environment/readiness status,
- bounded execution interface,
- sanitized/redacted errors,
- deterministic return state.

### 10.3 Future adapters

Future adapters must be optional.

Examples:

- Firebase
- Cloudflare
- Supabase CLI
- Docker
- Java
- Rust
- Go

No future adapter may be required merely to open an existing project that does not
use it.

---


## 10.4 Universal Generic Toolchain — FINAL LOCK Amendment

XP+ v1 must include a **Generic Toolchain Adapter** so projects are not limited to built-in Node, Python, PostgreSQL, or Git adapters.

The adapter must execute only commands explicitly declared by an approved project profile/policy; store commands as argv arrays rather than shell strings; default to non-shell execution; define purpose such as `verify`, `test`, `build`, `lint`, or `format-check`; support timeout and repo-scoped working directories; sanitize/redact output; reject undeclared commands and paths outside the repository; never infer business semantics; and never perform network/deployment actions automatically.

This is the universal escape hatch for Go, Rust, Java/Gradle/Maven, PHP/Composer, Flutter/Dart, Android/Gradle, .NET, React/Vue/Svelte/Next/Vite, static sites, monorepos, documentation/tooling repositories, and future ecosystems. Specialized adapters may still be added where stronger semantic controls are useful, but a new framework must not require a core XP change merely to run declared local verification commands.

The Universal Acceptance Suite must include at least one generic-toolchain fixture that is neither Node nor Python.

## 11. Recovery Model

Preserve current conservative recovery principle:

- verification/build/test may be safe to retry,
- source apply/database apply/locking are critical,
- ambiguous critical state must be audited rather than blindly replayed.

XP+ should improve recovery messages by including:

- interrupted operation,
- last known stage,
- affected project,
- current source fingerprint,
- recovery class,
- next safe action.

Remediation must continue matching active incident context.

---

## 12. Verification & QA

### 12.1 Verification authority

A project is WORK_READY only when:

- source adapter is valid,
- branch policy is valid,
- required commands are available,
- canonical verification is configured or explicitly marked unnecessary,
- project profile passes audit.

### 12.2 Empty verify policy

XP+ must no longer silently equate `source_verify: []` with a fully verified project.

Recommended behavior:

- during onboarding/audit: `PROFILE_INCOMPLETE` unless verification is explicitly waived,
- during package execution: preserve backward compatibility but emit a prominent
  warning or require policy acknowledgement for legacy profiles.

This avoids breaking old projects while fixing the readiness model.

### 12.3 Human QA

Human QA remains mandatory where declared by package/workflow.

Final Lock remains impossible if source changes after verification/safepoint.

---

## 13. Backward Compatibility Strategy

### 13.1 Legacy read path

XP+ must continue to read current:

- `.xp/project.json`,
- `.xp/policies.json`,
- `.xp/compatibility.json`,
- run state v1,
- checkpoint state,
- registry,
- control repo,
- package protocol v1.

### 13.2 Capability upgrades

New profile features must be additive.

Example:

```json
{
  "profile_version": 1,
  "runtimes": ["node", "python"]
}
```

continues to work.

Future optional fields may be ignored safely by older readers only when explicitly
designed as backward-compatible.

### 13.3 No automatic mass rewrite

XP+ must never rewrite every project's `.xp/` metadata on first launch.

---

## 14. Universal Acceptance Matrix

XP+ stable requires all of these fixture categories:

| Fixture | Required validation |
|---|---|
| Plain Git | registry, package, branch guard, safepoint, lock |
| Node | runtime discovery, npm verification |
| Python | runtime discovery, Python verification |
| Node + PostgreSQL | source verify + DB approval + SQL test |
| Firebase/static web | no PostgreSQL assumption |
| Segeran Jiwa POS Legacy | profile v1 continuity + corrective workflow |
| Segeran Jiwa POS Next | existing checkpoints + Node/Python/PostgreSQL workflow |

For Legacy and Next, testing must not mutate production data.

---

## 15. Acceptance Requirements for Segeran Jiwa POS Next

XP+ cannot be promoted if it fails to:

- load `segeran-jiwa-pos-next`,
- preserve `profile_version: 1`,
- preserve PostgreSQL adapter behavior,
- run `npm run verify`,
- preserve branch guards,
- read existing checkpoint history,
- preserve existing `LOCKED_REMOTE` runs,
- create a new WORK package,
- run DB approval flow in a fixture/non-production-safe context,
- create remote safepoint,
- record Human QA,
- Final Lock successfully,
- release remote lease,
- produce source archive and hashes.

---

## 16. Acceptance Requirements for Segeran Jiwa POS Legacy

XP+ cannot be promoted if it fails to:

- load `segeran-jiwa-pos-legacy`,
- identify its incomplete verification profile,
- recommend or apply an explicitly approved profile hardening,
- preserve Firebase as project concern rather than engine hardcoding,
- execute a WORK package on a `work/*` branch,
- reject protected-branch execution,
- produce checkpoint/recovery evidence,
- preserve rollback safety.

---

## 17. GitHub Release Discipline

GitHub sync is a required Final Lock gate for XP+.

### Development

XP+ development happens on an isolated engine branch/worktree.

Do not promote experimental engine code directly to stable.

### Stable release sync

The final GitHub release must include:

- source engine,
- updated handshake,
- generated schema documentation,
- changelog,
- compatibility matrix,
- upgrade/rollback documentation,
- installer/update path,
- release notes,
- version tag.

### Stable promotion rule

No stable tag until:

- universal fixtures PASS,
- Legacy compatibility PASS,
- Next compatibility PASS,
- engine upgrade rollback test PASS,
- clean install test PASS,
- upgrade-from-rc18.3 test PASS.

---

## 18. XP+ Roadmap

### XP+-00 — Compatibility Freeze
Lock this blueprint and create compatibility fixtures/snapshots.

### XP+-01 — Safe Engine Upgrade
Implement side-by-side candidate install, health checking, activation, and automatic
rollback.

### XP+-02 — Canonical Schema & AI Contract
Implement machine-readable schemas and generate handshake/docs from them.

### XP+-03 — Project Doctor & Smart Onboarding
Implement readiness audit, capability discovery, verify discovery, and explicit
profile update workflow.

### XP+-04 — Bundle v2
Compact default bundle plus `--deep`.

### XP+-05 — Capability/Adapter Hardening
Formalize adapter contracts and current built-in adapters.

### XP+-06 — Compatibility Reader Hardening
Regression-test profile v1, state v1, checkpoint history, package protocol v1, and
registry/control state.

### XP+-07 — Universal Acceptance Suite
Run fixture matrix plus Legacy and Next compatibility tests.

### XP+-08 — XP+ Release Candidate
Install XP+ in parallel, shadow-test, and validate upgrade/rollback.

### XP+-09 — XP+ Stable
Promote active engine only after all acceptance gates pass.

### XP+-10 — GitHub Release Sync
Push stable source/docs, create tag/release, publish compatibility and upgrade notes.

---

## 19. Implementation Boundaries

XP+ v1 explicitly does **not** include:

- production deployment automation,
- mandatory Firebase adapter,
- mandatory Cloudflare adapter,
- forced profile v2,
- forced state v2,
- package protocol v2,
- business-specific project logic,
- automatic project migration,
- remote SaaS dependency for basic operation.

These can be future work.

---

## 20. Definition of Done

XP+ v1 is complete when all are true:

1. Existing XP projects work without migration.
2. Existing Next checkpoints/runs remain readable.
3. Legacy profile incompleteness is detected accurately.
4. `xp schema` is authoritative.
5. handshake uses the same schema authority.
6. project doctor correctly distinguishes registered vs work-ready.
7. compact bundle is substantially smaller than current deep bundle.
8. deep bundle remains available for engine audits.
9. engine upgrade is side-by-side and rollback-capable.
10. Legacy compatibility suite passes.
11. Next compatibility suite passes.
12. generic fixture suite passes.
13. XP+ stable is synchronized to GitHub with release artifacts.

---

## 21. Design Self-Review

### Placeholder scan
PASS — no TBD/TODO requirements remain.

### Compatibility consistency
PASS — command remains `xp`, metadata remains `.xp/`, profile/state/protocol v1 remain
supported, and no forced migration is introduced.

### Scope check
PASS — XP+ v1 is a platform evolution. Implementation is intentionally split into
XP+-00 through XP+-10 rather than one monolithic package.

### Architecture consistency
PASS — all new features are expressed as generic workstation capabilities rather than
Segeran Jiwa business logic.

### Risk check
PASS — the highest-risk change, engine upgrade, is isolated before activation and
requires rollback tests.

---

## 22. Approval Record

This document is the FINAL LOCK design specification for XP+ v1.

**Approved by the user on 2026-09-13.**

Implementation must follow a test-first, backward-compatible plan. Any architectural
change that contradicts this blueprint requires a new explicit approval before implementation.
