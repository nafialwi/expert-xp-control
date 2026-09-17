# AF-03 Capability, Provenance & Activity Transparency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit capability state, opt-in Live Check, source/processor/via provenance, and persistent per-job Activity Trails to XP+ without weakening existing AF-02 AI routing, adapter readiness, recovery, package, workflow, or secret-safety behavior.

**Architecture:** Add two focused core modules: `xp.capabilities` for state snapshots and explicit live probing, and `xp.activity` for immutable provenance/activity records plus JSONL persistence. Integrate them at existing boundaries (`xp.ai`, adapters/readiness, CLI, test runner-facing workflow surfaces) without changing protocol-v1 project/package schemas or introducing background monitoring. AF-02 remains the AI execution boundary; AF-03 observes and reports it rather than replacing it.

**Tech Stack:** Python 3 standard library, dataclasses, enum, pathlib, json, datetime, unittest; existing XP+ Git/adapter/AI abstractions.

**Spec:** `docs/superpowers/specs/2026-09-17-af03-capability-provenance-activity-transparency.md`

## Global Constraints

- Base product line: XP+ `2.1.x`; preserve compatibility with stable `v2.1.0` baseline and all AF-00–AF-02 behavior.
- Standard library only; add no dependency.
- Normal readiness/status checks must remain local/offline.
- Live Check must run only after an explicit user action; no timer, daemon, polling loop, startup probe, or hidden HTTP request.
- Do not add silent AI/provider fallback. `AIGateway` continues to dispatch only the selected route.
- Preserve AF-02 separation of `AIRoute`, `AIRequest`, `AIResponse`, `AIReadiness`, `AITransport`, `AgentRuntime`, and existing transport behavior.
- Never persist API secret values, authorization headers, environment-secret contents, hidden prompts, scratchpads, or chain-of-thought.
- Preserve project/profile/state/package protocol v1; AF-03 activity storage is engine metadata, not a forced project migration.
- Do not weaken `GenericToolchainAdapter`, `PackageExecutor`, `WorkflowEngine`, recovery, deployment guards, or path/secret protections.
- `NOT_CHECKED != AVAILABLE`; `REQUESTED != COMPLETED`; `STARTED != COMPLETED`; `AI_GENERATED != LIVE`; `FALLBACK != ORIGINAL_PROVIDER`.
- Every functional change is test-first and each task ends with a green focused test set plus a commit.

---

## File Map

### New files

- `src/xp/capabilities.py` — canonical capability status types, snapshots, explicit live-probe coordinator, real-use failure downgrade.
- `src/xp/activity.py` — provenance types, immutable activity events, job trails, redaction/sanitization, JSONL persistence/readback.
- `tests/test_capabilities.py` — offline vs live semantics, timestamps, stale/real-use failure rules, no background probing.
- `tests/test_activity.py` — source/processor/via separation, event statuses, redaction, persistence, completed-job history.
- `tests/test_af03_ai_observability.py` — AF-02 AI integration, actual route/model recording, failed-provider behavior, no fallback.
- `tests/test_af03_cli.py` — user-visible status/live/history behavior and LIVE vs AI KNOWLEDGE rendering.
- `docs/superpowers/evidence/2026-09-17-af03-capability-provenance-activity-transparency.md` — final verification evidence generated only after all gates pass.

### Existing files expected to be modified

- `src/xp/ai/contracts.py` — only if a small non-secret readiness/result adapter is needed; do not change AF-02 request/response semantics.
- `src/xp/ai/gateway.py` — emit/return observable route/model outcome metadata through an injected recorder hook; no automatic fallback.
- `src/xp/ai/agents/base.py` — allow observable agent run/readiness outcome recording without provider-specific logic.
- `src/xp/readiness.py` — convert existing local readiness findings into canonical capability snapshots without initiating live network work.
- `src/xp/adapters/base.py` — expose existing adapter readiness into AF-03 canonical status mapping; preserve `capabilities()` and existing readiness call signatures.
- `src/xp/cli.py` — add explicit live-check trigger and activity/history rendering using existing CLI structure.
- `src/xp/paths.py` — add engine-owned activity/history path helper if no equivalent metadata path helper exists.
- `src/xp/models.py` — only if current job/run identity needs a stable accessor; do not change state_version.

### Files explicitly protected from behavioral redesign

- `src/xp/adapters/generic.py`
- `src/xp/executor.py`
- `src/xp/workflow.py`
- `src/xp/config.py`
- protocol-v1 package/schema files except imports needed for observation-only hooks

---

## Task 1 — Canonical Capability State and Offline Snapshot

**Files:**
- Create: `src/xp/capabilities.py`
- Create: `tests/test_capabilities.py`
- Modify: `src/xp/readiness.py`
- Modify: `src/xp/adapters/base.py`

**Interfaces:**
- Produces:

```python
class CapabilityState(str, Enum):
    AVAILABLE = "available"
    NEEDS_ATTENTION = "needs_attention"
    UNAVAILABLE = "unavailable"
    NOT_CHECKED = "not_checked"

@dataclass(frozen=True)
class CapabilitySnapshot:
    capability_id: str
    state: CapabilityState
    detail: str
    checked_at: datetime | None = None
    live: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

class CapabilityRegistry:
    def local_snapshot(self) -> tuple[CapabilitySnapshot, ...]: ...
    def record_runtime_failure(self, capability_id: str, detail: str, *, when: datetime | None = None) -> CapabilitySnapshot: ...
    def get(self, capability_id: str) -> CapabilitySnapshot: ...
```

- `local_snapshot()` must not call HTTP/network/live-provider methods.
- Existing adapter readiness remains the source for local runtime/environment facts.

- [ ] **Step 1: Write failing tests for canonical states and NOT_CHECKED semantics.**

```python
def test_unchecked_capability_is_not_available():
    registry = CapabilityRegistry()
    snapshot = registry.get("live-web")
    assert snapshot.state is CapabilityState.NOT_CHECKED
    assert snapshot.checked_at is None
    assert snapshot.live is False


def test_runtime_failure_downgrades_previous_available_state():
    registry = CapabilityRegistry(initial=(
        CapabilitySnapshot(
            capability_id="live-web",
            state=CapabilityState.AVAILABLE,
            detail="probe succeeded",
            checked_at=fixed_dt(),
            live=True,
        ),
    ))
    current = registry.record_runtime_failure("live-web", "request failed", when=later_dt())
    assert current.state is CapabilityState.NEEDS_ATTENTION
    assert current.detail == "request failed"
    assert current.checked_at == later_dt()
```

- [ ] **Step 2: Write a network-tripwire test proving local snapshots stay offline.** Inject a probe callable that raises `AssertionError("network must not run")`; call only `local_snapshot()` and assert no exception.
- [ ] **Step 3: Run `PYTHONPATH=src python -m unittest tests.test_capabilities -v` and confirm RED because `xp.capabilities` does not exist.**
- [ ] **Step 4: Implement `CapabilityState`, frozen `CapabilitySnapshot`, and `CapabilityRegistry` with deterministic in-memory state and UTC-aware timestamps.**
- [ ] **Step 5: Add a pure mapping helper from existing adapter/readiness results to `CapabilitySnapshot`; do not alter adapter capability names or readiness signatures.**
- [ ] **Step 6: Make `xp.readiness` consume/map the canonical snapshot type for presentation while keeping normal checks offline.**
- [ ] **Step 7: Re-run `tests.test_capabilities`, `tests.test_adapter_contract`, and `tests.test_project_doctor`; expected: PASS and no new network requirement.**
- [ ] **Step 8: Commit.**

```bash
git add src/xp/capabilities.py src/xp/readiness.py src/xp/adapters/base.py tests/test_capabilities.py
git commit -m "feat(af03): add canonical capability state"
```

---

## Task 2 — Explicit Live Check Coordinator

**Files:**
- Modify: `src/xp/capabilities.py`
- Modify: `tests/test_capabilities.py`
- Modify: `src/xp/ai/gateway.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class LiveProbe:
    capability_id: str
    run: Callable[[], CapabilitySnapshot]

class LiveCheckService:
    def __init__(self, registry: CapabilityRegistry, probes: tuple[LiveProbe, ...], *, now: Callable[[], datetime]): ...
    def run_explicit(self, capability_ids: tuple[str, ...] | None = None) -> tuple[CapabilitySnapshot, ...]: ...
```

- No constructor/startup side effect may invoke `LiveProbe.run`.
- Every returned live snapshot has `checked_at != None` and `live=True`.
- A failed probe returns or records `NEEDS_ATTENTION`/`UNAVAILABLE`; it never fabricates success.

- [ ] **Step 1: Add a failing test that constructing `LiveCheckService` executes zero probes.** Use a counter probe and assert count remains `0` until `run_explicit()`.
- [ ] **Step 2: Add a failing test that `run_explicit()` invokes only requested capabilities and stamps the supplied deterministic UTC time.**
- [ ] **Step 3: Add a failing test that a probe exception is normalized to `NEEDS_ATTENTION` with sanitized detail and does not propagate secret-looking values from an injected exception fixture.**
- [ ] **Step 4: Run `tests.test_capabilities` and confirm RED.**
- [ ] **Step 5: Implement `LiveProbe` and `LiveCheckService`; keep the service passive until `run_explicit()` is called.**
- [ ] **Step 6: Add an AF-02 AI-readiness probe adapter that calls only existing `AIGateway`/transport readiness behavior; do not add fallback or send a completion request merely to prove readiness.**
- [ ] **Step 7: Run `tests.test_capabilities tests.test_ai_gateway tests.test_openai_compatible_transport -v`; expected: PASS.**
- [ ] **Step 8: Commit.**

```bash
git add src/xp/capabilities.py src/xp/ai/gateway.py tests/test_capabilities.py
git commit -m "feat(af03): add explicit live capability checks"
```

---

## Task 3 — Provenance and Persistent Activity Trail

**Files:**
- Create: `src/xp/activity.py`
- Create: `tests/test_activity.py`
- Modify: `src/xp/paths.py`

**Interfaces:**

```python
class ActivityStatus(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_ATTENTION = "needs_attention"

class ActivityCategory(str, Enum):
    LOCAL = "local"
    PROJECT = "project"
    FILE = "file"
    GIT = "git"
    GITHUB = "github"
    LIVE_WEB = "live_web"
    AI = "ai"
    TOOL = "tool"
    AGENT = "agent"
    TEST = "test"
    USER = "user"
    SYSTEM = "system"

@dataclass(frozen=True)
class Provenance:
    source: str | None = None
    processor: str | None = None
    via: str | None = None
    live: bool = False

@dataclass(frozen=True)
class ActivityEvent:
    event_id: str
    job_id: str
    timestamp: datetime
    category: ActivityCategory
    action: str
    provenance: Provenance
    status: ActivityStatus
    result_summary: str
    metadata: dict[str, Any] = field(default_factory=dict)

class ActivityStore:
    def append(self, event: ActivityEvent) -> None: ...
    def list_for_job(self, job_id: str) -> tuple[ActivityEvent, ...]: ...
```

Storage contract:
- engine-owned path, not project source;
- append-only JSONL per job or append-only partitioned JSONL;
- deterministic decoding;
- malformed line produces an explicit readable error or skipped-corrupt-record finding, never silent success;
- sanitizer rejects/redacts secret-key fields and chain-of-thought-like reserved fields before persistence.

- [ ] **Step 1: Write failing tests proving source, processor, and via are independent fields.**
- [ ] **Step 2: Write failing tests for `STARTED != COMPLETED` and `FAILED != COMPLETED`; no renderer/store helper may collapse these statuses.**
- [ ] **Step 3: Write failing persistence round-trip test: append three events for one job, construct a fresh store, read the same three ordered events after the job is conceptually complete.**
- [ ] **Step 4: Write failing redaction tests for metadata keys matching `authorization`, `api_key`, `token`, `secret`, `password`, `chain_of_thought`, `scratchpad`, and `reasoning_content`; persisted serialized text must not contain fixture secret values.**
- [ ] **Step 5: Run `PYTHONPATH=src python -m unittest tests.test_activity -v` and confirm RED.**
- [ ] **Step 6: Implement immutable enums/dataclasses, sanitizer, JSONL codec, and `ActivityStore`. Use atomic parent-directory creation but append-only event writes; no project file is modified.**
- [ ] **Step 7: Add `xp.paths` helper for the engine-owned AF-03 history root. Keep existing path semantics unchanged.**
- [ ] **Step 8: Re-run `tests.test_activity` and existing path/config tests; expected PASS.**
- [ ] **Step 9: Commit.**

```bash
git add src/xp/activity.py src/xp/paths.py tests/test_activity.py
git commit -m "feat(af03): add persistent activity trails"
```

---

## Task 4 — Instrument AF-02 AI and Agent Boundaries Without Fallback

**Files:**
- Modify: `src/xp/ai/gateway.py`
- Modify: `src/xp/ai/agents/base.py`
- Create: `tests/test_af03_ai_observability.py`
- Modify: `tests/test_ai_gateway.py`
- Modify: `tests/test_agent_runtime_contract.py`

**Interfaces:**

```python
class ActivityRecorder(Protocol):
    def record(self, event: ActivityEvent) -> None: ...
```

- `AIGateway` accepts an optional recorder/callback with a no-op default so AF-02 callers remain source-compatible.
- On successful AI execution, record the actual `route_id`, returned `model`, processor/model identity, selected transport/via, and `COMPLETED`.
- On selected-route failure, record `FAILED` or `NEEDS_ATTENTION`, update capability runtime state, and re-raise the existing normalized AF-02 error.
- Never select another route automatically.
- `AgentRuntime` observation uses the same event model and does not add Qwen/Gemini/OpenAI-specific behavior to the abstract base.

- [ ] **Step 1: Add a failing test with two configured routes where route A fails; assert route B transport call count remains `0`.**
- [ ] **Step 2: Add a failing success test asserting one AI event records the exact selected route and the model actually returned by `AIResponse`, not a guessed/default model.**
- [ ] **Step 3: Add a failing error test asserting provider failure records a non-success event and `CapabilityRegistry.get("ai:<route_id>")` becomes `NEEDS_ATTENTION`.**
- [ ] **Step 4: Add an agent-boundary test proving a fake `AgentRuntime` can emit an observable result event without exposing prompt internals or hidden reasoning fields.**
- [ ] **Step 5: Run AF-02 + AF-03 AI tests and confirm RED on missing recorder integration.**
- [ ] **Step 6: Add the optional observation hooks with no-op defaults. Preserve all AF-02 public request/response contracts and exception types.**
- [ ] **Step 7: Re-run `tests.test_ai_contracts tests.test_ai_settings tests.test_openai_compatible_transport tests.test_ai_gateway tests.test_agent_runtime_contract tests.test_af03_ai_observability -v`; expected PASS.**
- [ ] **Step 8: Re-run generic toolchain guard tests to prove observation hooks did not create an alternate execution path.**
- [ ] **Step 9: Commit.**

```bash
git add src/xp/ai/gateway.py src/xp/ai/agents/base.py tests/test_ai_gateway.py tests/test_agent_runtime_contract.py tests/test_af03_ai_observability.py
git commit -m "feat(af03): record ai and agent provenance"
```

---

## Task 5 — CLI: Explicit Live Check and Job Activity History

**Files:**
- Modify: `src/xp/cli.py`
- Create: `tests/test_af03_cli.py`
- Modify: `src/xp/readiness.py`

**Interfaces:**

Use existing CLI parser conventions and add the smallest AF-03 surface:

```text
xp check --live
xp activity <job-id>
```

Behavior:
- `xp check` remains local/offline.
- `xp check --live` is the explicit user action that may invoke configured live probes.
- `xp activity <job-id>` reads persisted history only; it performs no live operation.
- Human output renders `Tersedia`, `Perlu perhatian`, `Tidak tersedia`, `Belum diperiksa` and includes last-check time where present.
- Provenance rendering distinguishes `LIVE` from `AI KNOWLEDGE`.

- [ ] **Step 1: Add a failing CLI test that plain `xp check` does not call a live-probe tripwire.**
- [ ] **Step 2: Add a failing CLI test that `xp check --live` invokes the configured probe exactly once and prints the returned last-check timestamp.**
- [ ] **Step 3: Add a failing rendering test: `NOT_CHECKED` prints `Belum diperiksa`, never `Tersedia`.**
- [ ] **Step 4: Add a failing provenance rendering test: event/source with `live=True` prints `LIVE`; `source="ai-knowledge", live=False` prints `AI KNOWLEDGE`.**
- [ ] **Step 5: Add a failing history test that `xp activity completed-job-1` renders previously persisted events after creating a fresh CLI/service instance.**
- [ ] **Step 6: Add a failing test for an unknown job id returning a non-zero/explicit not-found outcome rather than an empty successful history.**
- [ ] **Step 7: Run `tests.test_af03_cli` and confirm RED.**
- [ ] **Step 8: Implement parser wiring and renderers only; do not add startup/background polling.**
- [ ] **Step 9: Run `tests.test_af03_cli tests.test_cli_xp_plus tests.test_project_doctor tests.test_capabilities tests.test_activity -v`; expected PASS.**
- [ ] **Step 10: Commit.**

```bash
git add src/xp/cli.py src/xp/readiness.py tests/test_af03_cli.py
git commit -m "feat(af03): expose live check and activity history"
```

---

## Task 6 — Observable Test/Tool Result Metadata

**Files:**
- Modify only the smallest existing test/tool result boundary discovered during implementation; prefer an observation hook over workflow redesign.
- Modify: `src/xp/activity.py`
- Create or modify the focused test file next to that boundary.

**Interfaces:**

Provide canonical helpers that convert already-known objective results into event metadata without parsing hidden model reasoning:

```python
def test_result_metadata(*, passed: int, failed: int, skipped: int = 0) -> dict[str, int]: ...

def source_result_metadata(*, source_count: int) -> dict[str, int]: ...
```

- [ ] **Step 1: Write a failing unit test that `test_result_metadata(passed=38, failed=0, skipped=1)` round-trips through `ActivityStore` exactly as counts.**
- [ ] **Step 2: Write a failing unit test that `source_result_metadata(source_count=4)` persists as `{"source_count": 4}`.**
- [ ] **Step 3: Locate the existing boundary where XP already knows a verification/test command outcome; instrument only that boundary so the event records objective counts when they are already available. Do not build a general log parser.**
- [ ] **Step 4: Run the focused boundary tests plus `tests.test_activity`; confirm PASS.**
- [ ] **Step 5: Commit the minimal instrumentation.**

```bash
git add src/xp/activity.py src/xp tests
git commit -m "feat(af03): record objective activity metrics"
```

Before committing, narrow `git add` to the exact discovered source/test files; do not stage unrelated files.

---

## Task 7 — AF-03 Security, Compatibility, and Full Regression Gate

**Files:**
- Create: `docs/superpowers/evidence/2026-09-17-af03-capability-provenance-activity-transparency.md`
- No product code changes unless a failing gate exposes an AF-03 defect; fix such defects test-first in their owning task area.

- [ ] **Step 1: Run dedicated AF-03 tests.**

```bash
PYTHONPATH=src python -m unittest \
  tests.test_capabilities \
  tests.test_activity \
  tests.test_af03_ai_observability \
  tests.test_af03_cli \
  -v
```

Expected: 0 failures.

- [ ] **Step 2: Re-run AF-02 AI regression.**

```bash
PYTHONPATH=src python -m unittest \
  tests.test_ai_contracts \
  tests.test_ai_settings \
  tests.test_openai_compatible_transport \
  tests.test_ai_gateway \
  tests.test_agent_runtime_contract \
  -v
```

Expected: 0 failures and still no automatic route fallback.

- [ ] **Step 3: Re-run core safety/compatibility regression.**

```bash
PYTHONPATH=src python -m unittest \
  tests.test_adapter_contract \
  tests.test_project_doctor \
  tests.test_generic_toolchain \
  tests.test_generic_toolchain_qwen_guards \
  tests.test_backward_compatibility \
  -v
```

Expected: 0 failures; existing intentionally optional real-project smoke may remain skipped only if it was already optional before AF-03.

- [ ] **Step 4: Run full regression.**

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py' -v
```

Expected: 0 failures.

- [ ] **Step 5: Prove local mode stays offline.** Run the AF-03 network-tripwire tests and plain `xp check` CLI test; expected: no probe invocation.
- [ ] **Step 6: Secret/history scan.** Create fixture activity containing synthetic secret values, persist it through the production sanitizer, then assert none of those values exist in the history file. Also grep AF-03 persistence code/tests for prohibited fields `chain_of_thought`, `scratchpad`, `reasoning_content` and confirm they occur only in rejection/redaction tests or deny-lists, never as persisted schema fields.
- [ ] **Step 7: Protected-scope diff inspection.**

```bash
git diff v2.1.0 -- \
  src/xp/adapters/generic.py \
  src/xp/executor.py \
  src/xp/workflow.py \
  src/xp/config.py
```

Expected: no behavioral redesign caused by AF-03. If the actual AF-03 branch is based on post-v2.1.0 AF-02 commits, additionally compare against the AF-02 merge/base commit so unrelated historical AF-02 changes are not misattributed.

- [ ] **Step 8: Hygiene.**

```bash
git diff --check
git status --short
```

Expected before evidence commit: only the evidence file is uncommitted.

- [ ] **Step 9: Write verification evidence containing: exact branch and HEAD, AF-03 implementation commits, dedicated test counts, AF-02 regression result, full regression result, offline-tripwire result, secret/history scan result, protected-scope diff result, and explicit confirmation that no background probe or silent fallback exists.**
- [ ] **Step 10: Commit evidence.**

```bash
git add docs/superpowers/evidence/2026-09-17-af03-capability-provenance-activity-transparency.md
git commit -m "docs(af03): record verification evidence"
```

---

## Execution Preflight

Before Task 1, verify the actual repository state instead of assuming the previously recorded branch/commit is still current:

```bash
git status --short --branch
git log -1 --oneline --decorate
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py' -v
```

Do not start AF-03 from a dirty tree or a red AF-02/core regression. If the canonical development branch differs from the last recorded `work/xp-plus-v1`, create the AF-03 worktree/branch from the verified current canonical head rather than from historical `v2.1.0` directly.

## Self-Review

### Spec coverage

- Local/offline normal checks: Tasks 1, 5, 7.
- Explicit-only Live Check + timestamps: Tasks 2, 5, 7.
- `NOT_CHECKED` semantics and real-use failure downgrade: Tasks 1, 2, 4.
- No silent fallback: Tasks 4, 7.
- Source/processor/via separation: Task 3, exercised by Tasks 4–6.
- LIVE vs AI KNOWLEDGE: Task 5.
- Per-job Activity Trail and post-completion history: Tasks 3, 5.
- No chain-of-thought persistence: Tasks 3, 4, 7.
- Simple statuses and objective counts: Tasks 3, 6.
- No background monitoring: Tasks 2, 5, 7.
- Anti-fake-success semantics: Tasks 1, 3, 4, 5.

### Placeholder scan

No `TBD`, `TODO`, deferred implementation stub, or unspecified error-handling step remains in this plan. The only implementation-time discovery allowed is Task 6's selection of the already-existing verification/test result boundary; its required behavior and tests are fully specified and it explicitly forbids a general parser or workflow redesign.

### Type consistency

`CapabilitySnapshot`, `CapabilityRegistry`, `LiveCheckService`, `Provenance`, `ActivityEvent`, `ActivityStore`, and status/category enums are defined once and reused consistently across tasks. AI integration depends on an optional recorder hook and preserves AF-02 request/response contracts.

## Completion Condition

AF-03 is complete only after Task 7 is green and the evidence commit exists. A passing Live Check alone is not completion; persistence, no-fallback behavior, offline invariants, secret/redaction safety, history readback, and full regression are all mandatory.
