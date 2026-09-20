# XP Next — CP-00B Selective Reuse Audit

Status: SAFE CHECKPOINT
Date: 2026-09-20
Baseline: XP+ 2.1.0 commit 5cc52145c6d1cc6b435cac00bdbcf2f14370e23b
Planning parent: 598a662aba7c94820448ec93d38e0ad2ad88c19f

## Purpose

Decide what XP Next may inherit from XP+ 2.1.0 without inheriting the legacy GPT/package-driven product model.

This checkpoint is an audit only. It adds no XP Next runtime implementation.

## Classification meanings

- REUSE — contract/logic is sufficiently independent to preserve substantially as-is, after namespace/test relocation.
- ADAPT — valuable implementation exists, but storage, configuration, sandbox, or product contract must change before use.
- REWRITE — keep the idea/acceptance behavior, not the current implementation.
- DROP — must not enter the normal XP Next runtime path. It may remain readable only for legacy migration/forensics if later required.

## Executive decision

XP Next must be a fresh composition.

Do not branch the normal workflow from AutopilotController, WAITING_GPT, GPT handoff ZIPs, package scanning, or the XP+ terminal home flow.

The safest reuse strategy is to import small proven islands of capability behind new XP Next interfaces rather than copy the whole xp package.

## Reuse matrix

| Legacy area / module | Decision | Why | XP Next treatment |
|---|---|---|---|
| ai/contracts.py | REUSE | Small, provider-neutral immutable AI request/response/readiness contracts; no GPT coupling. | Preserve contract semantics; relocate under XP Next intelligence contracts. |
| ai/policy.py / ZeroCostPolicy | REUSE | Directly supports zero-cost-first and explicit paid approval. | Make this a mandatory policy in the new Reasoning Broker. |
| ai/agents/base.py / AgentRuntime | REUSE | Worker contract is clean and replaceable; no provider hardcoding. | Keep worker interface; Hermes remains an adapter, never the control plane. |
| capabilities.py | REUSE | Local state is passive; explicit live check; no hidden probe. | Use as the semantic basis of the new Capability Registry. |
| redaction.py | REUSE | Small deterministic secret/redaction primitive. | Keep as common safety utility and extend tests as connectors appear. |
| recovery_manifest.py | REUSE | Portable source identity, strict validation, path/secret guards. | Preserve format concepts; introduce a new XP Next schema/version instead of silently mutating v1. |
| recovery_bundle.py | ADAPT | Good fail-closed bundle/checksum behavior, but payload set must include XP Next SQLite/artifacts safely. | Reuse validation patterns; redesign payload contract. |
| recovery_import.py | ADAPT | Strong traversal/checksum/destination guards. | Rebind to XP Next state import and new recovery schema. |
| recovery_device.py | ADAPT | Device-independent restore behavior is valuable. | Keep repo/branch/SHA verification; change state reconstruction for XP Next. |
| activity.py | ADAPT | Event/provenance model is strong, but persistence is file/path based. | Keep event semantics; store canonical Activity Trail in SQLite. |
| adapters/base.py | ADAPT | Capability/readiness abstraction is useful. | Fold into the new Tool Registry contract. |
| adapters/git.py | ADAPT | Proven Git state/safepoint logic. | Wrap as structured tools; do not expose raw Git commands to normal users/workers. |
| adapters/generic.py | ADAPT | Bounded command/redaction patterns are useful but generic shell execution is too broad. | Replace free-form command use with allowlisted structured tools. |
| adapters/node.py | ADAPT | Useful deterministic build/test execution. | Register bounded Node actions in Tool Registry. |
| adapters/python_runtime.py | ADAPT | Useful deterministic Python execution/readiness. | Register bounded Python actions in Tool Registry. |
| adapters/postgresql.py | ADAPT | SQL classification/safety concepts are useful. | Keep database work outside M1; later expose only explicit structured DB actions. |
| project_registry.py | ADAPT | Project identity/profile concepts are useful; persistence is JSON/path based. | Canonical project registry moves to SQLite; Git remains source authority. |
| project_doctor.py | ADAPT | Discovery and verifier-candidate logic are useful and tested. | Separate detection from mutation; write findings into new capability/project state. |
| project_context.py | ADAPT | Session/project resolution idea is useful. | Replace implicit legacy session rules with explicit active project in SQLite. |
| worker_governance.py | ADAPT | Approval, workspace boundaries, mutation audit, verifier, rollback concepts are strong. | Preserve safety contract but require SandboxBackend, structured tool scope, sanitized HOME/env, timeout, and explicit network policy. |
| ai/gateway.py | ADAPT | Transport/policy/readiness enforcement is useful. | Remove coupling to old job-state/settings stores; Reasoning Broker owns routing. |
| ai/hybrid_routing.py | ADAPT | No-silent-fallback, privacy/cost/quota decisions are valuable. | Simplify: deterministic first, local AI default, online optional with explicit permission. |
| ai/agents/local_backends.py | ADAPT | Qwen/9Router bindings prove local OpenAI-compatible paths. | Remove hardcoded runtime assumptions from core; discover/configure via capabilities. |
| ai/agents/default_wiring.py | ADAPT | Useful bridge pattern but still requires explicit old gateway/route/model wiring. | Replace with boot-time capability discovery and a default local reasoning route. |
| engine_lifecycle.py | ADAPT | Side-by-side install, health gate, activation and rollback are proven. | Reintroduce after core product loop exists; bind to XP Next layout and acceptance. |
| checkpoint.py | ADAPT | Checksum/redaction/evidence concepts remain valuable. | Checkpoints become job/recovery records in SQLite plus Git/source identity. |
| journal.py | REWRITE | Before/after journal concept matters, but file journal is not canonical state. | Transactional job/activity/recovery records in SQLite. |
| locks.py | REWRITE | Writer exclusion is required. | SQLite leases/locks with explicit owner/expiry; later device lease support. |
| models.py | REWRITE | Current run model encodes legacy stages. | New universal Job state model: DRAFT, PLANNING, READY, AWAITING_APPROVAL, RUNNING, VERIFYING, READY_TO_REVIEW, APPLYING, VERIFYING_APPLIED, COMPLETED plus NEEDS_ATTENTION, ROLLED_BACK, CANCELLED. |
| state_store.py | REWRITE | File state conflicts with the new single-authority requirement. | SQLite becomes canonical XP operational state. |
| orchestration.py | REWRITE | Bounded-plan/recovery/verifier concepts are good, but runtime depends on supplied retriever/planner/executor/remediator callbacks. It is a framework, not the native XP brain. | Build native Intent → Context → Planner → Reasoning Broker → Executor → Verifier loop; selectively reuse data-model ideas. |
| executor.py | DROP | Executor is tied to legacy declarative package application. | New executor runs structured tools/jobs inside sandbox; legacy package apply is not a normal path. |
| packages.py | DROP | Package-centric work flow made outside GPT artifacts first-class. | No package required for ordinary XP Next work. Keep only isolated legacy migration reader if later needed. |
| pkgbuild.py | DROP | Explicitly tied to package and WAITING_GPT remediation. | Do not port. |
| handoff.py | DROP | Explicit GPT handoff format and role model. | No ChatGPT/GPT handoff in the normal workflow. |
| workflow.py | DROP | Legacy state machine contains WAITING_GPT, package, lock and remote stages. | Replace entirely with the universal Job state machine. |
| autopilot.py | DROP | 1138-line package-driven supervisor; failure paths intentionally move to WAITING_GPT. | Do not use as XP Next brain. Retain only as frozen legacy reference. |
| control.py | DROP | Legacy remote control-state/lease model is coupled to old run state and remote branch behavior. | New local SQLite authority; device/remote lease designed later. |
| compatibility.py | DROP from core | Contains legacy state/package/GPT incident readers. | If migration is needed, isolate it in a one-way legacy importer, never in core runtime. |
| onboarding.py | REWRITE | Current onboarding is profile-package oriented. | New onboarding: inspect project → propose capabilities/verifier → user confirms → register. |
| visual_workstation.py | REWRITE | Visual snapshot mirrors legacy engine terminology. | New UX uses human concepts: task, progress, result, permission, review; Developer Mode may reveal internals. |
| visual_server.py | REWRITE | Stable server is mostly static/status GET. | New loopback local API with explicit job/actions and responsive PWA. |
| cli.py | DROP as product surface | 2400+ lines and many GPT references; normal UX exposes legacy concepts. | Keep only a small developer/recovery CLI in XP Next; PWA is primary surface. |

## Explicit dependency islands approved for extraction

### Island A — zero-cost intelligence contracts

Approved source concepts:

- ai/contracts.py
- ai/policy.py
- ai/agents/base.py
- capabilities.py
- redaction.py

Rule: these may be the first candidates for controlled extraction because they have no GPT workflow coupling and small dependency surfaces.

### Island B — portable recovery primitives

Approved source concepts:

- recovery_manifest.py
- recovery_bundle.py
- recovery_import.py
- recovery_device.py

Rule: preserve fail-closed validation/checksum/path/secret behavior, but do not carry legacy state-store payload assumptions into XP Next.

### Island C — project/tool discovery

Approved source concepts:

- project_doctor.py
- project_registry.py data concepts
- adapters/base.py
- adapters/git.py
- bounded Node/Python/PostgreSQL adapter patterns

Rule: all execution becomes structured Tool Registry actions. No arbitrary shell tool is a default XP Next capability.

### Island D — governed worker safety

Approved source concepts:

- worker_governance.py
- ActivityEvent / provenance semantics
- verification-before-success
- recovery-before-mutation
- bounded remediation
- protected source checking

Rule: this island cannot be activated until XP Next has a SandboxBackend. cwd remains context, never permission.

## Legacy contamination boundaries

The following must not be dependencies of XP Next M1 core:

- autopilot.py
- handoff.py
- pkgbuild.py
- packages.py
- workflow.py
- legacy control.py
- legacy cli.py
- legacy visual snapshot/server
- WAITING_GPT
- XP_GPT_* artifacts
- normal user flow that asks the user to download/upload remediation packages

A future compatibility importer may read old formats, but imported data must be translated one-way into XP Next canonical state.

## State authority for XP Next

Planned authority split:

- Git — source code identity/history.
- SQLite — XP operational state: projects, jobs, steps, approvals, activities, recovery points, artifacts, devices, preferences, automations.
- Filesystem — project files and generated artifacts.
- External/cloud services — optional connectors only, never canonical core state.

Chat transcripts are never canonical operational state.

## Zero-cost implications

The mandatory M1 path must remain:

1. deterministic local tools;
2. local capability discovery;
3. Local Qwen for reasoning when required;
4. Hermes/local worker for bounded implementation;
5. local verifier;
6. local review/apply/recovery.

9Router, Supabase relay, GitHub, cloud AI, Telegram, WhatsApp and other network services are optional accelerators/connectors, not core dependencies.

## Validation evidence

### Preflight

- Branch: planning/xp-next-bootstrap
- Parent planning commit: 598a662aba7c94820448ec93d38e0ad2ad88c19f
- Worktree clean before audit.
- Remote planning SHA matched local parent SHA.
- XP+ stable source was read-only.

### Static audit

Observed notable module characteristics:

- ai/contracts.py: 90 LOC, no GPT references.
- ai/policy.py: 69 LOC, no GPT references.
- capabilities.py: 206 LOC, no GPT references.
- worker_governance.py: 432 LOC, no GPT references.
- orchestration.py: 567 LOC, no GPT references but callback-driven rather than a complete native brain.
- autopilot.py: 1138 LOC, direct legacy handoff/workflow dependencies and GPT-coupled failure flow.
- cli.py: 2418 LOC, 34 direct GPT/WAITING_GPT/XP_GPT references detected by the audit.
- handoff.py: explicit XP_GPT artifact and GPT role/instruction contract.

### Targeted tests

The first targeted test invocation failed before running the selected tests because PYTHONPATH=src was omitted and imports could not resolve xp. This was an audit-command environment error, not a source/test failure. No source was changed.

The corrected invocation used PYTHONPATH=<worktree>/src and ran 111 targeted tests covering:

- Activity/provenance
- capabilities
- project doctor
- recovery manifest/bundle/import/device
- governed worker
- AI contracts
- hybrid routing
- orchestration
- engine lifecycle

Result: Ran 111 tests — OK.

The duplicate ZIP-member warning in one tamper test is expected test behavior and the test passed.

## CP-00B acceptance

PASS requires all of the following:

- classification matrix recorded;
- GPT-coupled legacy paths explicitly quarantined;
- reuse dependency islands identified;
- zero-cost mandatory path preserved;
- no XP Next runtime code created;
- XP+ stable source unchanged;
- no Segeran Jiwa mutation;
- no database migration;
- no production deployment;
- planning branch committed and pushed with exact remote SHA verification.

## Next allowed checkpoint

CP-01A — XP Next Skeleton Design + Test Contract

CP-01A must still remain small:

- decide XP Next package/repository namespace and minimal directory layout;
- define SQLite schema v1 at design/test-contract level;
- define minimal CLI/API contracts: version, doctor, status;
- define canonical Job state enum;
- define ZERO_COST_INDEPENDENCE acceptance fixture;
- create tests first where practical;
- do not integrate Qwen/Hermes yet;
- do not build the PWA yet.

Implementation must stop again after the CP-01A skeleton/test-contract safe checkpoint.
