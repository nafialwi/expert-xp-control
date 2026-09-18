# AF-04 Zero-Cost + Model Usage Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce XP's zero-cost AI policy before provider execution, persist explicit job-scoped approvals and model-switch state, capture objective usage evidence, and produce transparent model recommendations without silent fallback or fabricated confidence.

**Architecture:** Keep the existing AF-02 gateway and AF-03 observability boundaries. Add small provider-neutral modules under `src/xp/ai/` for policy, persistent job state, cost evidence, usage history, recommendation evidence, and presentation. `AIGateway.complete()` remains the execution boundary: route selection happens first, AF-04 policy runs second, transport execution happens only after an ALLOW decision, and objective observations are recorded after success/failure.

**Tech Stack:** Python standard library only, `unittest`, dataclasses/enums, JSON/JSONL local persistence, existing XP activity/capability contracts.

**Spec:** `docs/superpowers/specs/2026-09-18-af04-zero-cost-model-usage-policy.md`

## Global Constraints

- Baseline: `work/xp-plus-v1 @ 308f78f159704e72bb2d378b4c6f0da59702face`.
- Zero-cost is mandatory: known paid routes never reach transport.
- Unknown cost is not free; it requires explicit job-scoped route/model approval.
- No silent AI/provider/model fallback.
- One active model per job at a time; explicit user-approved switching is allowed.
- Live cost verification is explicit-only; no startup/background/polling checks.
- Online free-cost evidence becomes stale after 30 days but remains usable.
- Missing usage stays unavailable; it must never be rewritten as zero.
- Configured/requested model and provider-reported/served model remain distinct.
- Activity Trail records observable events only; no hidden reasoning or chain-of-thought.
- User feedback is optional and distinct from technical success.
- Historical recommendation claims require at least 5 comparable jobs.
- Feedback-quality claims require at least 3 comparable jobs with explicit feedback.
- UI/CLI presentation is compact by default with an expanded-detail form.
- Standard library only; do not add third-party dependencies.
- Protected files MUST remain unchanged unless the design is explicitly reopened:
  - `src/xp/adapters/generic.py`
  - `src/xp/executor.py`
  - `src/xp/workflow.py`
  - `src/xp/config.py`
- Preserve protocol v1, package execution semantics, GenericToolchain boundaries, AF-02 no-fallback behavior, and AF-03 capability/provenance/activity semantics.

---

## File Map

### New production files

- `src/xp/ai/policy.py`
  - Canonical cost-policy decisions.
  - `PolicyDecisionKind`, `PolicyDecision`, `ZeroCostPolicy`.
  - Pure logic only; no network and no persistence.

- `src/xp/ai/job_state.py`
  - Persistent job-scoped AI state.
  - Unknown-cost approvals.
  - Active route/model.
  - Explicit model-switch history.
  - Completion closes approvals.

- `src/xp/ai/cost_evidence.py`
  - Persistent declared-vs-observed cost evidence.
  - 30-day freshness calculation for online evidence.
  - No live network implementation.

- `src/xp/ai/usage_history.py`
  - Sanitized cross-job usage records.
  - Task categories.
  - User feedback.
  - Objective aggregation primitives.

- `src/xp/ai/recommendation.py`
  - Recommendation evidence and confidence rules.
  - No synthetic score.

- `src/xp/ai/presentation.py`
  - Compact/expanded human-readable formatting.
  - Indonesian user-facing cost/status language.

### Existing production files modified

- `src/xp/ai/gateway.py`
  - Enforce policy before transport.
  - Measure latency.
  - Capture configured vs served model.
  - Record observable AF-04 activity.
  - Never silently retry through another route/model.

- `src/xp/ai/contracts.py`
  - Only if needed to make unknown token fields explicit rather than implicit zero.
  - Do not change route cost-class vocabulary.

- `src/xp/paths.py`
  - Add focused helpers for AF-04 local state/history roots.

- `src/xp/cli.py`
  - Add minimal AF-04 inspection/decision surfaces without turning CLI into the security boundary.

### New tests

- `tests/test_af04_policy.py`
- `tests/test_af04_job_state.py`
- `tests/test_af04_cost_evidence.py`
- `tests/test_af04_gateway_enforcement.py`
- `tests/test_af04_usage_history.py`
- `tests/test_af04_recommendation.py`
- `tests/test_af04_presentation.py`
- `tests/test_af04_cli.py`
- `tests/test_af04_integration.py`

### Documentation/evidence

- `docs/superpowers/evidence/2026-09-18-af04-zero-cost-model-usage-policy.md`

---

### Task 1: Canonical Zero-Cost Policy Contracts

**Files:**
- Create: `src/xp/ai/policy.py`
- Create: `tests/test_af04_policy.py`
- Read-only reference: `src/xp/ai/contracts.py`
- Read-only reference: `src/xp/ai/settings.py`

**Interfaces:**
- Consumes: existing `AIRoute` with `route_id`, `model`, and `cost_class`.
- Produces:
  - `PolicyDecisionKind(Enum)` with `ALLOW`, `BLOCK`, `REQUIRE_APPROVAL`.
  - `PolicyDecision` dataclass with `kind`, `route_id`, `model`, `cost_class`, `reason`.
  - `ZeroCostPolicy.evaluate(route: AIRoute, *, approved_unknown: bool = False) -> PolicyDecision`.

- [ ] **Step 1: Write failing tests for free, paid, and unknown**

```python
import unittest

from xp.ai.contracts import AIRoute
from xp.ai.policy import PolicyDecisionKind, ZeroCostPolicy


def route(cost_class: str) -> AIRoute:
    return AIRoute(
        route_id="r1",
        transport="openai-compatible",
        base_url="https://example.invalid/v1",
        model="example/model",
        secret_env="EXAMPLE_KEY",
        cost_class=cost_class,
    )


class AF04PolicyTests(unittest.TestCase):
    def test_free_route_is_allowed(self):
        decision = ZeroCostPolicy().evaluate(route("free"))
        self.assertEqual(decision.kind, PolicyDecisionKind.ALLOW)

    def test_paid_route_is_hard_blocked_even_if_approval_is_claimed(self):
        decision = ZeroCostPolicy().evaluate(
            route("paid"),
            approved_unknown=True,
        )
        self.assertEqual(decision.kind, PolicyDecisionKind.BLOCK)

    def test_unknown_route_requires_approval(self):
        decision = ZeroCostPolicy().evaluate(route("unknown"))
        self.assertEqual(
            decision.kind,
            PolicyDecisionKind.REQUIRE_APPROVAL,
        )

    def test_unknown_route_is_allowed_only_with_explicit_approval(self):
        decision = ZeroCostPolicy().evaluate(
            route("unknown"),
            approved_unknown=True,
        )
        self.assertEqual(decision.kind, PolicyDecisionKind.ALLOW)
```

- [ ] **Step 2: Run the dedicated test and verify RED**

Run:

```bash
PYTHONPATH=src python -m unittest -v tests.test_af04_policy
```

Expected: FAIL because `xp.ai.policy` does not exist.

- [ ] **Step 3: Implement the minimal pure policy module**

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .contracts import AIRoute


class PolicyDecisionKind(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


@dataclass(frozen=True)
class PolicyDecision:
    kind: PolicyDecisionKind
    route_id: str
    model: str
    cost_class: str
    reason: str


class ZeroCostPolicy:
    def evaluate(
        self,
        route: AIRoute,
        *,
        approved_unknown: bool = False,
    ) -> PolicyDecision:
        if route.cost_class == "paid":
            return PolicyDecision(
                PolicyDecisionKind.BLOCK,
                route.route_id,
                route.model,
                route.cost_class,
                "Known paid routes are blocked by zero-cost policy.",
            )
        if route.cost_class == "unknown" and not approved_unknown:
            return PolicyDecision(
                PolicyDecisionKind.REQUIRE_APPROVAL,
                route.route_id,
                route.model,
                route.cost_class,
                "Cost is not verified; explicit job approval is required.",
            )
        return PolicyDecision(
            PolicyDecisionKind.ALLOW,
            route.route_id,
            route.model,
            route.cost_class,
            "Route is allowed by zero-cost policy.",
        )
```

- [ ] **Step 4: Run the dedicated test and verify GREEN**

Run:

```bash
PYTHONPATH=src python -m unittest -v tests.test_af04_policy
```

Expected: all Task 1 tests PASS.

- [ ] **Step 5: Run AF-02 route/settings regression**

Run:

```bash
PYTHONPATH=src python -m unittest -v tests.test_ai_settings
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/xp/ai/policy.py tests/test_af04_policy.py
git diff --cached --check
git commit -m "feat(af04): add zero-cost policy contracts"
```

---

### Task 2: Persistent Job-Scoped Approval and Active Model State

**Files:**
- Create: `src/xp/ai/job_state.py`
- Modify: `src/xp/paths.py`
- Create: `tests/test_af04_job_state.py`

**Interfaces:**
- Consumes: job id, route id, configured model.
- Produces:
  - `UnknownCostApproval(route_id: str, model: str)`.
  - `ModelSwitch(previous_route_id, previous_model, new_route_id, new_model, timestamp, reason)`.
  - `JobAIState(job_id, active_route_id, active_model, approved_unknown, switches, completed)`.
  - `JobAIStateStore.for_home(home: Path)`.
  - `get(job_id) -> JobAIState`.
  - `save(state) -> None`.
  - `approve_unknown(job_id, route_id, model) -> JobAIState`.
  - `is_unknown_approved(job_id, route_id, model) -> bool`.
  - `switch_model(...) -> JobAIState`.
  - `complete(job_id) -> JobAIState`.

- [ ] **Step 1: Write failing persistence/lifecycle tests**

```python
import tempfile
import unittest
from pathlib import Path

from xp.ai.job_state import JobAIStateStore


class AF04JobStateTests(unittest.TestCase):
    def test_unknown_approval_survives_store_reopen_for_same_job(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            first = JobAIStateStore.for_home(home)
            first.approve_unknown("job-1", "r1", "model-a")

            second = JobAIStateStore.for_home(home)
            self.assertTrue(
                second.is_unknown_approved("job-1", "r1", "model-a")
            )
            self.assertFalse(
                second.is_unknown_approved("job-2", "r1", "model-a")
            )
            self.assertFalse(
                second.is_unknown_approved("job-1", "r1", "model-b")
            )

    def test_completed_job_expires_unknown_approval(self):
        with tempfile.TemporaryDirectory() as td:
            store = JobAIStateStore.for_home(Path(td))
            store.approve_unknown("job-1", "r1", "model-a")
            store.complete("job-1")
            self.assertFalse(
                store.is_unknown_approved("job-1", "r1", "model-a")
            )

    def test_model_switch_requires_explicit_call_and_records_history(self):
        with tempfile.TemporaryDirectory() as td:
            store = JobAIStateStore.for_home(Path(td))
            store.set_active_model("job-1", "r1", "model-a")
            state = store.switch_model(
                "job-1",
                new_route_id="r2",
                new_model="model-b",
                reason="hasil kurang sesuai",
            )
            self.assertEqual(state.active_route_id, "r2")
            self.assertEqual(state.active_model, "model-b")
            self.assertEqual(len(state.switches), 1)
```

- [ ] **Step 2: Run and verify RED**

```bash
PYTHONPATH=src python -m unittest -v tests.test_af04_job_state
```

Expected: FAIL because job-state module/store does not exist.

- [ ] **Step 3: Add one AF-04 path helper**

In `src/xp/paths.py`, add a focused helper that resolves under:

```text
~/.expert-workstation/state/ai/
```

Use the same home-expansion/resolution style already used in `paths.py`.

Required public helper:

```python
def ai_state_root(home: Path) -> Path:
    ...
```

It must not alter existing path semantics.

- [ ] **Step 4: Implement atomic JSON state persistence**

Implementation requirements:

```python
@dataclass(frozen=True)
class UnknownCostApproval:
    route_id: str
    model: str


@dataclass(frozen=True)
class ModelSwitch:
    previous_route_id: str
    previous_model: str
    new_route_id: str
    new_model: str
    timestamp: str
    reason: str | None


@dataclass(frozen=True)
class JobAIState:
    job_id: str
    active_route_id: str | None = None
    active_model: str | None = None
    approved_unknown: UnknownCostApproval | None = None
    switches: tuple[ModelSwitch, ...] = ()
    completed: bool = False
```

Store one sanitized JSON document per job using a SHA-256-derived filename, mirroring AF-03's safe filename approach. Write through a temporary file then `replace()` so interrupted writes do not leave a partial state document.

`complete(job_id)` MUST:
- set `completed=True`;
- clear `approved_unknown`;
- retain model-switch history for audit/recovery.

- [ ] **Step 5: Run dedicated tests and verify GREEN**

```bash
PYTHONPATH=src python -m unittest -v tests.test_af04_job_state
```

Expected: PASS.

- [ ] **Step 6: Run existing path/activity regressions**

```bash
PYTHONPATH=src python -m unittest -v \
  tests.test_activity \
  tests.test_af03_ai_observability
```

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/xp/ai/job_state.py src/xp/paths.py tests/test_af04_job_state.py
git diff --cached --check
git commit -m "feat(af04): persist job ai policy state"
```

---

### Task 3: Enforce Zero-Cost Policy Before Transport

**Files:**
- Modify: `src/xp/ai/gateway.py`
- Create: `tests/test_af04_gateway_enforcement.py`
- Read-only reference: `src/xp/activity.py`
- Read-only reference: `src/xp/ai/policy.py`
- Read-only reference: `src/xp/ai/job_state.py`

**Interfaces:**
- Consumes:
  - `ZeroCostPolicy.evaluate(...)`.
  - `JobAIStateStore.is_unknown_approved(...)`.
- Produces:
  - `AIPolicyBlockedError` or equivalent AF-04-specific error exposed from the policy/gateway boundary.
  - observable Activity Trail event for allow/block/approval-required outcomes.
- Critical invariant: a BLOCK or REQUIRE_APPROVAL decision must result in zero calls to `transport.complete()`.

- [ ] **Step 1: Write failing transport-call-count tests**

```python
import unittest

from xp.ai.contracts import AIRequest
from xp.ai.policy import AIPolicyBlockedError


class CountingTransport:
    def __init__(self):
        self.calls = 0

    def complete(self, route, request):
        self.calls += 1
        raise AssertionError("transport should not have been called")


class AF04GatewayEnforcementTests(unittest.TestCase):
    def test_paid_route_never_reaches_transport(self):
        gateway, transport = self.make_gateway(cost_class="paid")
        with self.assertRaises(AIPolicyBlockedError):
            gateway.complete(AIRequest(messages=({"role": "user", "content": "x"},)))
        self.assertEqual(transport.calls, 0)

    def test_unknown_route_without_job_approval_never_reaches_transport(self):
        gateway, transport = self.make_gateway(cost_class="unknown")
        with self.assertRaises(AIPolicyBlockedError):
            gateway.complete(
                AIRequest(messages=({"role": "user", "content": "x"},)),
            )
        self.assertEqual(transport.calls, 0)
```

The test helper must construct real `AISettings`/`AIGateway` objects using the existing AF-02 test style; do not bypass route selection.

- [ ] **Step 2: Run and verify RED**

```bash
PYTHONPATH=src python -m unittest -v tests.test_af04_gateway_enforcement
```

Expected: FAIL because gateway does not yet enforce AF-04 policy.

- [ ] **Step 3: Inject policy/state dependencies into AIGateway without breaking defaults**

Extend `AIGateway.__init__` with optional provider-neutral dependencies:

```python
policy: ZeroCostPolicy | None = None
job_state_store: JobAIStateStore | None = None
```

Keep AF-02 callers valid. Do not create automatic alternate routes.

For an unknown route, approval is true only when all of these match:
- current job id;
- selected route id;
- selected configured model.

If the current gateway API does not carry job id, add one explicit optional keyword parameter to `complete()`:

```python
job_id: str | None = None
```

Unknown routes with no `job_id` are not approved.

- [ ] **Step 4: Enforce decision before `_transport_for()`/`transport.complete()` side effects**

Required execution order:

```text
route()
-> resolve job approval
-> policy.evaluate()
-> if not ALLOW: record observable event and raise
-> resolve/use transport
-> transport.complete()
```

Do not perform transport readiness/network activity before the ALLOW gate.

- [ ] **Step 5: Record objective policy activity**

Use existing AF-03 `ActivityEvent`/`Provenance` patterns.

Metadata must include only safe fields such as:

```python
{
    "route_id": route.route_id,
    "model": route.model,
    "cost_class": route.cost_class,
    "policy_decision": decision.kind.value,
}
```

Do not write prompt content, API credentials, or hidden reasoning.

- [ ] **Step 6: Run dedicated tests and verify GREEN**

```bash
PYTHONPATH=src python -m unittest -v tests.test_af04_gateway_enforcement
```

Expected: PASS and blocked tests prove transport call count is zero.

- [ ] **Step 7: Run AF-02/AF-03 gateway regressions**

```bash
PYTHONPATH=src python -m unittest -v \
  tests.test_ai_gateway \
  tests.test_af03_ai_observability
```

Expected: PASS.

- [ ] **Step 8: Commit Task 3**

```bash
git add src/xp/ai/gateway.py src/xp/ai/policy.py tests/test_af04_gateway_enforcement.py
git diff --cached --check
git commit -m "feat(af04): enforce zero-cost policy before transport"
```

---

### Task 4: Cost Evidence and 30-Day Freshness

**Files:**
- Create: `src/xp/ai/cost_evidence.py`
- Create: `tests/test_af04_cost_evidence.py`
- Modify: `src/xp/paths.py` only if a second focused path helper is necessary.

**Interfaces:**
- Produces:
  - `CostScope(Enum)` with `LOCAL`, `ONLINE`, `UNKNOWN`.
  - `CostEvidence(route_id, observed_cost_class, verified_at, source, scope)`.
  - `CostEvidenceStore.for_home(home)`.
  - `put(evidence)`.
  - `get(route_id) -> CostEvidence | None`.
  - `is_stale(evidence, *, now) -> bool`.
  - `effective_cost_class(route, evidence) -> str`.

- [ ] **Step 1: Write failing freshness/effective-cost tests**

```python
import unittest
from datetime import datetime, timedelta, timezone

from xp.ai.cost_evidence import (
    CostEvidence,
    CostScope,
    is_stale,
)


class AF04CostEvidenceTests(unittest.TestCase):
    def test_online_free_evidence_becomes_stale_after_30_days(self):
        now = datetime(2026, 9, 18, tzinfo=timezone.utc)
        evidence = CostEvidence(
            route_id="r1",
            observed_cost_class="free",
            verified_at=now - timedelta(days=31),
            source="provider-docs",
            scope=CostScope.ONLINE,
        )
        self.assertTrue(is_stale(evidence, now=now))

    def test_online_free_evidence_is_not_blocked_only_because_stale(self):
        # effective value remains free; staleness is presentation metadata.
        ...

    def test_local_evidence_does_not_expire(self):
        ...
```

Replace the ellipses with concrete assertions before running the test. Required assertions:
- stale online free still resolves to effective `free`;
- local evidence returns `False` from `is_stale` regardless of age.

- [ ] **Step 2: Run and verify RED**

```bash
PYTHONPATH=src python -m unittest -v tests.test_af04_cost_evidence
```

Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement evidence store with explicit scope**

Rules:
- never infer `LOCAL` from `127.0.0.1`, `localhost`, or URL shape;
- accept only cost states `free`, `paid`, `unknown`;
- persist source + timestamp + scope;
- persistent writes occur only through explicit store calls from an approved caller;
- this module performs no network access.

Freshness function:

```python
COST_EVIDENCE_MAX_AGE = timedelta(days=30)

def is_stale(evidence: CostEvidence, *, now: datetime) -> bool:
    if evidence.scope is not CostScope.ONLINE:
        return False
    return now - evidence.verified_at > COST_EVIDENCE_MAX_AGE
```

- [ ] **Step 4: Run dedicated tests and verify GREEN**

```bash
PYTHONPATH=src python -m unittest -v tests.test_af04_cost_evidence
```

Expected: PASS.

- [ ] **Step 5: Add explicit no-network test**

Patch/guard `urllib.request.urlopen` and construct/read cost evidence. Assert the guard was never invoked.

- [ ] **Step 6: Commit Task 4**

```bash
git add src/xp/ai/cost_evidence.py src/xp/paths.py tests/test_af04_cost_evidence.py
git diff --cached --check
git commit -m "feat(af04): persist cost evidence and freshness"
```

---

### Task 5: Objective Usage Capture, Latency, and Served-Model Mismatch

**Files:**
- Modify: `src/xp/ai/gateway.py`
- Modify: `src/xp/ai/contracts.py` only if token fields currently cannot express absence.
- Create: `tests/test_af04_usage_history.py`
- Create: `src/xp/ai/usage_history.py`

**Interfaces:**
- Produces `UsageRecord` with:
  - `job_id`;
  - `route_id`;
  - `transport`;
  - `configured_model`;
  - `served_model`;
  - `task_category`;
  - `effective_cost_class`;
  - `latency_ms`;
  - `input_tokens: int | None`;
  - `output_tokens: int | None`;
  - `total_tokens: int | None`;
  - `status`;
  - `error_type: str | None`;
  - `feedback`;
  - timestamp.
- `UsageHistoryStore.append(record)`.
- `UsageHistoryStore.list_records(...)`.

- [ ] **Step 1: Write failing tests for missing usage and served model**

```python
class AF04UsageHistoryTests(unittest.TestCase):
    def test_missing_provider_usage_stays_none(self):
        record = self.make_record(
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
        )
        self.assertIsNone(record.input_tokens)
        self.assertIsNone(record.output_tokens)
        self.assertIsNone(record.total_tokens)

    def test_configured_and_served_model_are_distinct_fields(self):
        record = self.make_record(
            configured_model="requested/model",
            served_model="served/model-v2",
        )
        self.assertEqual(record.configured_model, "requested/model")
        self.assertEqual(record.served_model, "served/model-v2")
```

- [ ] **Step 2: Run and verify RED**

```bash
PYTHONPATH=src python -m unittest -v tests.test_af04_usage_history
```

Expected: FAIL because usage-history module does not exist.

- [ ] **Step 3: Implement sanitized append-only local usage history**

Use JSONL under an AF-04 state/history directory.

Sanitization must reject/drop known secret-bearing keys consistent with AF-03:
- authorization;
- api_key;
- token values that are credentials rather than token counts;
- secret_env values;
- chain_of_thought;
- scratchpad;
- reasoning_content.

Token-count fields are numeric usage metadata and remain allowed.

- [ ] **Step 4: Add monotonic latency measurement around one allowed transport call**

In `AIGateway.complete()`:
- record monotonic start immediately before `transport.complete()`;
- compute latency after success or caught failure;
- never use wall-clock subtraction for duration.

Inject a monotonic callable for deterministic unit tests if necessary:

```python
monotonic: Callable[[], float] | None = None
```

- [ ] **Step 5: Add served-model mismatch activity**

If `response.model` materially differs from `route.model`:
- store both;
- record AF-03-compatible `NEEDS_ATTENTION`;
- do not rewrite the response model;
- do not silently select a different route for the next call.

The mismatch rule must be exact-string based in AF-04. Do not invent alias equivalence heuristics.

- [ ] **Step 6: Run dedicated tests and verify GREEN**

```bash
PYTHONPATH=src python -m unittest -v \
  tests.test_af04_usage_history \
  tests.test_af04_gateway_enforcement
```

Expected: PASS.

- [ ] **Step 7: Run OpenAI-compatible transport regression**

```bash
PYTHONPATH=src python -m unittest -v tests.test_ai_transport
```

If the actual AF-02 transport test module has a different filename, use the existing module containing `OpenAICompatibleTransport` tests discovered by:

```bash
grep -RIl 'OpenAICompatibleTransport' tests | sort
```

Run only the discovered existing transport test module(s); do not rename them for AF-04.

- [ ] **Step 8: Commit Task 5**

```bash
git add \
  src/xp/ai/gateway.py \
  src/xp/ai/contracts.py \
  src/xp/ai/usage_history.py \
  tests/test_af04_usage_history.py
git diff --cached --check
git commit -m "feat(af04): capture objective ai usage"
```

If `contracts.py` did not need a change, omit it from `git add`.

---

### Task 6: Task Category and Optional User Feedback

**Files:**
- Modify: `src/xp/ai/usage_history.py`
- Create or extend: `tests/test_af04_usage_history.py`

**Interfaces:**
- Produces:
  - `TaskCategory` enum:
    - `CODING_DEBUGGING`
    - `AUDIT_REVIEW`
    - `ANALYSIS_REASONING`
    - `RESEARCH_WEB`
    - `DOCUMENT_WRITING`
    - `DATA_SPREADSHEET`
    - `DESIGN_VISUAL`
    - `GENERAL`
  - `UserFeedback` enum:
    - `GOOD`
    - `OK`
    - `NOT_SUITABLE`
    - `UNRATED`
  - `correct_category(record_id, category)`.
  - `set_feedback(record_id, feedback, reason=None)`.

- [ ] **Step 1: Write failing tests proving feedback is not inferred**

```python
def test_technical_success_does_not_create_positive_feedback(self):
    record = self.make_record(status="completed")
    self.assertEqual(record.feedback, UserFeedback.UNRATED)

def test_category_correction_is_explicit(self):
    original = self.make_record(task_category=TaskCategory.GENERAL)
    corrected = self.store.correct_category(
        original.record_id,
        TaskCategory.CODING_DEBUGGING,
    )
    self.assertEqual(
        corrected.task_category,
        TaskCategory.CODING_DEBUGGING,
    )
```

- [ ] **Step 2: Run and verify RED**

```bash
PYTHONPATH=src python -m unittest -v tests.test_af04_usage_history
```

Expected: FAIL for missing enums/update methods.

- [ ] **Step 3: Implement explicit category/feedback updates**

Requirements:
- new records default to `GENERAL` unless a caller supplies another category;
- feedback defaults to `UNRATED`;
- `completed` status never changes feedback;
- correction/update writes a new observable history revision/event rather than silently mutating the historical meaning;
- optional negative-feedback reason is plain user-provided metadata.

- [ ] **Step 4: Add AF-03 activity integration for corrections/feedback**

Record only:
- record/job id;
- previous/new category;
- feedback label;
- optional reason.

Do not store hidden reasoning or raw prompt text.

- [ ] **Step 5: Run dedicated and AF-03 activity tests**

```bash
PYTHONPATH=src python -m unittest -v \
  tests.test_af04_usage_history \
  tests.test_activity
```

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

```bash
git add src/xp/ai/usage_history.py tests/test_af04_usage_history.py
git diff --cached --check
git commit -m "feat(af04): add task category and user feedback"
```

---

### Task 7: Evidence-Based Recommendation Engine

**Files:**
- Create: `src/xp/ai/recommendation.py`
- Create: `tests/test_af04_recommendation.py`
- Read-only reference: `src/xp/ai/usage_history.py`

**Interfaces:**
- Produces:
  - `RecommendationConfidence(Enum)` with `INITIAL`, `HISTORY`.
  - `RecommendationEvidence`.
  - `ModelRecommendation`.
  - `recommend(records, *, category, eligible_models) -> tuple[ModelRecommendation, ...]`.
- No numeric synthetic quality score.

- [ ] **Step 1: Write failing minimum-sample tests**

```python
class AF04RecommendationTests(unittest.TestCase):
    def test_four_jobs_cannot_claim_history_confidence(self):
        records = self.records_for("model-a", count=4)
        rec = self.recommend_one(records)
        self.assertEqual(
            rec.confidence,
            RecommendationConfidence.INITIAL,
        )

    def test_five_comparable_jobs_can_use_history(self):
        records = self.records_for("model-a", count=5)
        rec = self.recommend_one(records)
        self.assertEqual(
            rec.confidence,
            RecommendationConfidence.HISTORY,
        )

    def test_feedback_quality_claim_requires_three_feedback_jobs(self):
        records = self.records_for(
            "model-a",
            count=5,
            feedback_count=2,
        )
        rec = self.recommend_one(records)
        self.assertFalse(rec.evidence.feedback_quality_available)
```

- [ ] **Step 2: Run and verify RED**

```bash
PYTHONPATH=src python -m unittest -v tests.test_af04_recommendation
```

Expected: FAIL because recommendation module does not exist.

- [ ] **Step 3: Implement aggregation without a magic score**

Evidence fields must include:
- comparable job count;
- technical success count;
- failure count;
- explicit feedback count;
- good/ok/not-suitable counts;
- median latency when available;
- sample-size warning when models have unequal evidence.

Ordering may use deterministic policy priorities:
1. zero-cost eligible only;
2. task/category compatibility supplied by caller;
3. history confidence when threshold is met;
4. technical success proportion only when sample threshold is met;
5. user feedback evidence only when at least 3 feedback-bearing comparable jobs exist;
6. stable model id as final deterministic tie-breaker.

Do not expose the internal ordering as a synthetic score.

- [ ] **Step 4: Add unequal-sample test**

Create evidence for:
- model A: 8 comparable jobs;
- model B: 3 comparable jobs.

Assert the rendered evidence for model B contains a limitation flag such as:

```python
limited_history is True
```

and no "better than" claim is generated solely from the unequal datasets.

- [ ] **Step 5: Run tests and verify GREEN**

```bash
PYTHONPATH=src python -m unittest -v tests.test_af04_recommendation
```

Expected: PASS.

- [ ] **Step 6: Commit Task 7**

```bash
git add src/xp/ai/recommendation.py tests/test_af04_recommendation.py
git diff --cached --check
git commit -m "feat(af04): add evidence-based model recommendations"
```

---

### Task 8: Explicit Model Switching and Observable Handoff

**Files:**
- Modify: `src/xp/ai/job_state.py`
- Create: `tests/test_af04_integration.py`
- Modify: `src/xp/ai/gateway.py` only if gateway must consult active-model state.

**Interfaces:**
- Consumes:
  - job state active route/model;
  - explicit `switch_model(...)`.
- Produces:
  - `ModelHandoff` containing only observable job state.
  - explicit mismatch/block when caller tries a non-active model without a recorded switch.

- [ ] **Step 1: Write failing active-model guard test**

```python
def test_job_cannot_silently_change_model(self):
    self.store.set_active_model("job-1", "r1", "model-a")

    with self.assertRaises(ModelSwitchRequiredError):
        self.gateway.complete(
            self.request,
            route_id="r2",
            job_id="job-1",
        )

    self.assertEqual(self.transport_r2.calls, 0)
```

- [ ] **Step 2: Write failing explicit-switch test**

```python
def test_explicit_switch_allows_new_model_and_records_transition(self):
    self.store.set_active_model("job-1", "r1", "model-a")
    self.store.switch_model(
        "job-1",
        new_route_id="r2",
        new_model="model-b",
        reason="hasil kurang sesuai",
    )

    response = self.gateway.complete(
        self.request,
        route_id="r2",
        job_id="job-1",
    )

    self.assertEqual(response.route_id, "r2")
    self.assertEqual(len(self.store.get("job-1").switches), 1)
```

- [ ] **Step 3: Run and verify RED**

```bash
PYTHONPATH=src python -m unittest -v tests.test_af04_integration
```

Expected: FAIL because active-model guard/handoff are incomplete.

- [ ] **Step 4: Implement observable handoff type**

Required fields:

```python
@dataclass(frozen=True)
class ModelHandoff:
    goal: str
    resources: tuple[str, ...]
    decisions: tuple[str, ...]
    produced_results: tuple[str, ...]
    observed_errors: tuple[str, ...]
    progress_summary: str
    next_action: str | None
```

Do not add fields named or semantically equivalent to:
- chain_of_thought;
- reasoning;
- scratchpad;
- hidden rationale.

- [ ] **Step 5: Add sanitizer test for handoff**

Construct user/job metadata containing keys:
- `chain_of_thought`;
- `scratchpad`;
- `reasoning_content`.

Assert they cannot enter persisted handoff/activity state.

- [ ] **Step 6: Run integration tests and verify GREEN**

```bash
PYTHONPATH=src python -m unittest -v \
  tests.test_af04_integration \
  tests.test_af04_gateway_enforcement \
  tests.test_activity
```

Expected: PASS.

- [ ] **Step 7: Commit Task 8**

```bash
git add \
  src/xp/ai/job_state.py \
  src/xp/ai/gateway.py \
  tests/test_af04_integration.py
git diff --cached --check
git commit -m "feat(af04): require explicit model switching"
```

If `gateway.py` did not need an additional change in this task, omit it.

---

### Task 9: Compact/Expanded Presentation and Minimal CLI Surfaces

**Files:**
- Create: `src/xp/ai/presentation.py`
- Modify: `src/xp/cli.py`
- Create: `tests/test_af04_presentation.py`
- Create: `tests/test_af04_cli.py`

**Interfaces:**
- Produces:
  - `format_cost_label(cost_class: str) -> str`.
  - `format_usage_compact(record) -> str`.
  - `format_usage_expanded(record) -> str`.
  - `format_recommendation_compact(rec) -> str`.
  - `format_recommendation_expanded(rec) -> str`.
- CLI inspection surfaces:
  - `xp ai-usage <job-id> [--expand]`
  - `xp ai-recommend <category> [--expand]`
- CLI remains presentation/control wiring, not the enforcement boundary.

- [ ] **Step 1: Write failing presentation tests**

```python
class AF04PresentationTests(unittest.TestCase):
    def test_unknown_cost_uses_plain_language(self):
        self.assertEqual(
            format_cost_label("unknown"),
            "Biaya belum diketahui",
        )

    def test_missing_tokens_render_as_not_available(self):
        rendered = format_usage_expanded(
            self.record(input_tokens=None, output_tokens=None)
        )
        self.assertIn("Tidak tersedia", rendered)
        self.assertNotIn("Input token     0", rendered)

    def test_compact_output_does_not_dump_full_metadata(self):
        rendered = format_usage_compact(self.record())
        self.assertIn("AI", rendered)
        self.assertNotIn("Provenance", rendered)
```

- [ ] **Step 2: Run and verify RED**

```bash
PYTHONPATH=src python -m unittest -v tests.test_af04_presentation
```

Expected: FAIL because presentation module does not exist.

- [ ] **Step 3: Implement compact/expanded formatters**

Required labels:

```python
{
    "free": "Gratis",
    "paid": "Berbayar",
    "unknown": "Biaya belum diketahui",
}
```

Expanded usage must show when available:
- category;
- route/transport;
- configured model;
- served model;
- input/output/total token counts or `Tidak tersedia`;
- latency;
- effective cost;
- cost verification age/staleness;
- feedback;
- provenance summary.

- [ ] **Step 4: Write failing CLI tests**

Use the repo's existing CLI invocation test style.

Assertions:
- `xp ai-usage job-1` uses compact formatter;
- `xp ai-usage job-1 --expand` uses expanded formatter;
- `xp ai-recommend "Coding / Debugging"` reports "Belum cukup data" when history threshold is not met;
- CLI does not trigger live cost verification.

- [ ] **Step 5: Implement minimal CLI wiring**

Do not add automatic network calls.

If a requested job/history record does not exist, return a clear non-success result without fabricating a record.

- [ ] **Step 6: Run presentation/CLI tests and verify GREEN**

```bash
PYTHONPATH=src python -m unittest -v \
  tests.test_af04_presentation \
  tests.test_af04_cli
```

Expected: PASS.

- [ ] **Step 7: Run AF-03 CLI regressions**

```bash
PYTHONPATH=src python -m unittest -v tests.test_af03_cli
```

Expected: PASS.

- [ ] **Step 8: Commit Task 9**

```bash
git add \
  src/xp/ai/presentation.py \
  src/xp/cli.py \
  tests/test_af04_presentation.py \
  tests/test_af04_cli.py
git diff --cached --check
git commit -m "feat(af04): expose transparent ai usage views"
```

---

### Task 10: AF-04 Integration Gates, Protected Scope, and Evidence

**Files:**
- Create: `docs/superpowers/evidence/2026-09-18-af04-zero-cost-model-usage-policy.md`
- Modify tests only if a verification gap is found; do not weaken assertions.
- Protected files remain read-only.

**Interfaces:**
- Produces final objective evidence for review/PR.
- No new runtime feature should be introduced in this task.

- [ ] **Step 1: Run all dedicated AF-04 tests**

```bash
PYTHONPATH=src python -m unittest -v \
  tests.test_af04_policy \
  tests.test_af04_job_state \
  tests.test_af04_cost_evidence \
  tests.test_af04_gateway_enforcement \
  tests.test_af04_usage_history \
  tests.test_af04_recommendation \
  tests.test_af04_presentation \
  tests.test_af04_cli \
  tests.test_af04_integration
```

Expected: PASS.

Record:
- number of tests;
- elapsed time;
- skipped count.

- [ ] **Step 2: Run AF-02 regression suite**

Use the existing AF-02 test modules already present in the repository. At minimum include:

```bash
PYTHONPATH=src python -m unittest -v \
  tests.test_ai_contracts \
  tests.test_ai_settings \
  tests.test_ai_gateway
```

Then discover any additional existing AF-02 AI tests with:

```bash
find tests -maxdepth 1 -type f -name 'test_ai_*.py' -print | sort
```

Run every discovered AF-02 AI test module. Expected: PASS.

- [ ] **Step 3: Run AF-03 regression suite**

```bash
PYTHONPATH=src python -m unittest -v \
  tests.test_activity \
  tests.test_capabilities \
  tests.test_af03_ai_observability \
  tests.test_af03_cli \
  tests.test_af03_verification_activity
```

Expected: PASS.

- [ ] **Step 4: Run full suite**

```bash
PYTHONPATH=src python -m unittest discover \
  -s tests \
  -p 'test_*.py' \
  -v
```

Expected: PASS. The exact total may be greater than the AF-03 baseline of 182 because AF-04 adds tests.

- [ ] **Step 5: Prove blocked routes cannot touch transport**

Run focused tests with call counters:

```bash
PYTHONPATH=src python -m unittest -v \
  tests.test_af04_gateway_enforcement.AF04GatewayEnforcementTests.test_paid_route_never_reaches_transport \
  tests.test_af04_gateway_enforcement.AF04GatewayEnforcementTests.test_unknown_route_without_job_approval_never_reaches_transport
```

Expected: PASS.

- [ ] **Step 6: Prove no automatic live cost network path**

Run the cost-evidence no-network test with a guard that fails on `urllib.request.urlopen`.

Expected: PASS.

- [ ] **Step 7: Verify protected files are byte-for-byte unchanged from baseline**

```bash
git diff --exit-code \
  308f78f159704e72bb2d378b4c6f0da59702face \
  -- \
  src/xp/adapters/generic.py \
  src/xp/executor.py \
  src/xp/workflow.py \
  src/xp/config.py
```

Expected: no output, exit code 0.

Also capture hashes:

```bash
sha256sum \
  src/xp/adapters/generic.py \
  src/xp/executor.py \
  src/xp/workflow.py \
  src/xp/config.py
```

Expected baseline hashes:

```text
46265e421df168430b33429abe9f9ddd3db4c927d11ec7691bc9db7ac75ec4ed  src/xp/adapters/generic.py
22a20b055b41ab1bfef67eb9fcbece537e281995928e396405ff2afcff756ffe  src/xp/executor.py
ff75df691debfca99c9a7245d36c7316d1b1f9c92de83c455109c1596bbdeaec  src/xp/workflow.py
75d7236112b4c461d235a391afd9466a5ca724ed5783395c3272d3fe86206bb8  src/xp/config.py
```

- [ ] **Step 8: Scan for prohibited hidden-reasoning persistence**

```bash
git grep -n -E \
  'chain_of_thought|reasoning_content|scratchpad' \
  -- src/xp tests
```

Any matches must be limited to:
- sanitizer deny-lists;
- docstrings explaining prohibition;
- negative tests proving removal.

There must be no persisted schema field carrying hidden reasoning.

- [ ] **Step 9: Scan for accidental automatic fallback**

```bash
git grep -n -i \
  -E 'fallback|retry.*route|alternate.*route|switch.*automatic' \
  -- src/xp/ai tests
```

Review every match. No production path may select another route/model after failure without an explicit user-approved switch.

- [ ] **Step 10: Run whitespace and worktree hygiene gates**

```bash
git diff --check
git status --short
```

Before evidence commit, expected changed files are only intended AF-04 implementation/tests/docs.

- [ ] **Step 11: Write final evidence document**

The evidence file must state:
- baseline commit `308f78f159704e72bb2d378b4c6f0da59702face`;
- AF-04 branch;
- dedicated test results;
- AF-02 regression results;
- AF-03 regression results;
- full-suite result;
- paid/unknown transport-block proof;
- no-automatic-live-check proof;
- protected-file diff result and hashes;
- no-silent-fallback review result;
- hidden-reasoning persistence scan result;
- final worktree status.

Do not claim a gate passed without fresh command output.

- [ ] **Step 12: Validate and commit evidence**

```bash
git add docs/superpowers/evidence/2026-09-18-af04-zero-cost-model-usage-policy.md
git diff --cached --check
git commit -m "docs(af04): record verification evidence"
```

- [ ] **Step 13: Run final post-evidence full suite**

```bash
PYTHONPATH=src python -m unittest discover \
  -s tests \
  -p 'test_*.py' \
  -v
```

Expected: PASS.

- [ ] **Step 14: Final clean-state verification**

```bash
git status --porcelain
git --no-pager log -12 --oneline --decorate
```

Expected:
- status output empty;
- AF-04 task commits visible in order;
- branch remains `work/af04-zero-cost-usage`.

---

## Commit Boundary Summary

Expected implementation commits, one reviewable unit each:

```text
feat(af04): add zero-cost policy contracts
feat(af04): persist job ai policy state
feat(af04): enforce zero-cost policy before transport
feat(af04): persist cost evidence and freshness
feat(af04): capture objective ai usage
feat(af04): add task category and user feedback
feat(af04): add evidence-based model recommendations
feat(af04): require explicit model switching
feat(af04): expose transparent ai usage views
docs(af04): record verification evidence
```

Do not squash task boundaries during implementation. They are intended to support review, regression diagnosis, and rollback.

## Plan Self-Review Result

- Spec coverage: all AF-04 spec sections map to Tasks 1–10.
- Placeholder scan: clean; no implementation step contains unresolved placeholder markers or unspecified behavior.
- Type consistency: policy, job state, cost evidence, usage history, recommendation, handoff, and presentation interfaces are named once and consumed consistently by later tasks.
- Scope: AF-04 remains one coherent subsystem centered on zero-cost model usage policy; real Qwen execution and autonomous multi-model orchestration remain out of scope.
- Protected scope: explicit verification is included in Task 10.
- TDD: every runtime task begins with failing tests and ends with focused regressions plus a commit.
