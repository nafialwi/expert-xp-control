# CP-09B PWA ↔ XP Next Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a resumable, loopback-only visual gateway over XP Next so the PWA can create a governed work session, pause for human decisions, reach `READY_TO_REVIEW`, and later Apply or Discard through existing XP Next safety controls.

**Architecture:** Persist resumable visual-session metadata beside canonical XP Next jobs, split the existing zero-cost E2E path at the review boundary while preserving `ZeroCostE2EService.run()`, add a `WorkSessionService` that owns state transitions, and expose only that service through a same-origin loopback HTTP gateway. The browser never owns project mutation, Git operations, verification, Apply/Discard, or recovery.

**Tech Stack:** Python 3.11+, stdlib `sqlite3`, `dataclasses`, `json`, `http.server.ThreadingHTTPServer`, `secrets`, existing XP Next services, stdlib `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-23-cp09b-pwa-xp-next-convergence-design.md`

## Global Constraints

- PWA remains loopback-only during CP-09B.
- Visual gateway rejects `0.0.0.0` and non-loopback bind addresses.
- No production deploy, branch merge, release, or production database action is introduced.
- PWA never edits/copies project files and never performs Git mutation directly.
- Worker confirmation, sandbox approval, and Apply/Discard remain explicit human decisions.
- Existing source-HEAD and review-fingerprint guards remain authoritative.
- No silent worker or AI fallback.
- Browser JSON never includes credentials, tokens, hidden reasoning, raw worker prompts, verifier argv, internal sandbox paths, or unrestricted environment data.
- Segeran Jiwa production is excluded from CP-09B tests.
- Existing XP Next and AF-10 visual regressions must remain green.

## File Structure

- Modify `next/src/xp_next/state_schema.py`: schema v2 plus v1→v2 local-state migration.
- Modify `next/src/xp_next/state_store.py`: bounded work-session persistence with optimistic revision.
- Create `next/src/xp_next/work_session.py`: work-session model, public projection, allowed actions.
- Modify `next/src/xp_next/zero_cost_e2e.py`: pause-at-review and finalize-review phases; preserve `run()`.
- Create `next/src/xp_next/work_session_service.py`: resumable governed orchestration.
- Create `next/src/xp_next/visual_gateway.py`: same-origin loopback JSON gateway.
- Modify `next/src/xp_next/cli.py`: development command `visual-gateway`; no final `xp` cutover.
- Create `next/tests/test_cp09b_session_store.py`.
- Create `next/tests/test_cp09b_execution_phases.py`.
- Create `next/tests/test_cp09b_work_session_service.py`.
- Create `next/tests/test_cp09b_visual_gateway.py`.
- Create `next/tests/test_cp09b_e2e.py`.
- Create `docs/xp-next/CP09B_PWA_XP_NEXT_CONVERGENCE.md`.

## Review Focus

1. A retried/stale POST must not repeat an approval, worker run, Apply, or Discard.
2. Reopening runtime at worker approval, sandbox approval, or `READY_TO_REVIEW` must resume without rerunning prior mutations.
3. Original Git HEAD drift after review must block Apply and never overwrite the drift.
4. Missing/corrupt session payload or missing sandbox after review must fail closed as `NEEDS_ATTENTION`.
5. Invalid Host/Origin, wrong content type, or missing/invalid same-origin session cookie must be rejected before mutation-service dispatch.

---

### Task 1: Durable Session Store and v1→v2 Migration

**Files:**
- Modify: `next/src/xp_next/state_schema.py`
- Modify: `next/src/xp_next/state_store.py`
- Create: `next/tests/test_cp09b_session_store.py`

**Interfaces:**
- Consumes: existing `jobs` table and `StateStore.get_job()`.
- Produces:
  - `create_work_session(job_id, payload) -> dict`
  - `get_work_session(job_id: str) -> dict[str, object]`
  - `list_work_sessions(limit: int = 20) -> list[dict[str, object]]`
  - `update_work_session(job_id: str, payload: dict[str, object], *, expected_revision: int) -> dict[str, object]`
  - schema version 2, with v1 upgrade in place.

- [ ] **Step 1: Write the RED migration/concurrency tests**

Use this v1 database helper in the new test file:

```python
def make_v1_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta(key, value) VALUES('schema_version', '1');
        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            root_path TEXT NOT NULL UNIQUE,
            source_kind TEXT NOT NULL,
            active INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            user_goal TEXT NOT NULL,
            state TEXT NOT NULL,
            risk TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO projects VALUES(
            'p1','Fixture','/tmp/fixture','git',1,'now','now'
        );
        INSERT INTO jobs VALUES(
            'j1','p1','goal','DRAFT','write','now','now'
        );
        """
    )
    connection.commit()
    connection.close()
```

Tests:

```python
def test_v1_database_upgrades_without_losing_job(self):
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "state.sqlite3"
        make_v1_database(db)
        with StateStore(db) as store:
            self.assertEqual(store.get_job("j1")["user_goal"], "goal")
            session = store.create_work_session("j1", {"phase": "PREPARED"})
            self.assertEqual(session["revision"], 1)
            version = store.connection.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()[0]
            self.assertEqual(version, "2")

def test_stale_revision_is_rejected(self):
    session = store.create_work_session("j1", {"phase": "PREPARED"})
    fresh = store.update_work_session(
        "j1",
        {"phase": "WORKER_CONFIRMED"},
        expected_revision=int(session["revision"]),
    )
    self.assertEqual(fresh["revision"], 2)
    with self.assertRaises(StateStoreError):
        store.update_work_session(
            "j1",
            {"phase": "STALE"},
            expected_revision=1,
        )
```

- [ ] **Step 2: Run RED**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/next/src" python3 -m unittest next.tests.test_cp09b_session_store -v
```

Expected: FAIL because schema v2/work-session APIs do not exist.

- [ ] **Step 3: Implement schema v2 explicitly**

In `state_schema.py` set `SCHEMA_VERSION = 2` and add:

```python
_WORK_SESSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS work_sessions (
    job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK(revision >= 1),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

def _upgrade_v1_to_v2(connection: sqlite3.Connection) -> None:
    with connection:
        connection.executescript(_WORK_SESSION_SCHEMA)
        connection.execute(
            "UPDATE meta SET value='2' WHERE key='schema_version'"
        )
```

`initialize_schema()` behavior:
- fresh DB: create base schema + `work_sessions`, write version 2;
- version 1: call `_upgrade_v1_to_v2()`;
- version 2: ensure tables exist;
- any other version: raise `SchemaVersionError`.

- [ ] **Step 4: Implement exact bounded persistence**

In `state_store.py` import `json` and add:

```python
def _encode_session_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(encoded.encode("utf-8")) > 256_000:
        raise StateStoreError("work session payload exceeds 256000 bytes")
    return encoded

def create_work_session(
    self,
    job_id: str,
    payload: dict[str, object],
) -> dict[str, object]:
    self.get_job(job_id)
    now = _utc_now()
    encoded = _encode_session_payload(payload)
    with self.connection:
        self.connection.execute(
            """
            INSERT INTO work_sessions(
                job_id, revision, payload_json, created_at, updated_at
            ) VALUES(?,1,?,?,?)
            """,
            (job_id, encoded, now, now),
        )
    return self.get_work_session(job_id)
```

`get_work_session()` returns `job_id`, integer `revision`, decoded `payload`, `created_at`, `updated_at`.

`list_work_sessions()` uses `ORDER BY updated_at DESC, job_id`, rejects `limit < 1`, clamps values above 100 to 100, and decodes each payload through the same decoder as `get_work_session()`.

`update_work_session()` uses:

```python
cursor = self.connection.execute(
    """
    UPDATE work_sessions
    SET payload_json=?, revision=revision+1, updated_at=?
    WHERE job_id=? AND revision=?
    """,
    (encoded, now, job_id, expected_revision),
)
if cursor.rowcount != 1:
    raise StateStoreError("work session revision changed; refresh state")
```

- [ ] **Step 5: Add restart persistence and 256000-byte bound tests**

Close/reopen the same DB and verify revision/payload. Also assert an oversized payload raises `StateStoreError`, and create two sessions to verify `list_work_sessions(limit=1)` returns only the most recently updated row.

- [ ] **Step 6: Run Task 1 and full next regression**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/next/src" python3 -m unittest next.tests.test_cp09b_session_store -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/next/src" python3 -m unittest discover -s next/tests -q
```

- [ ] **Step 7: Commit**

```bash
git add next/src/xp_next/state_schema.py next/src/xp_next/state_store.py   next/tests/test_cp09b_session_store.py
git commit -m "feat(xp-next): persist resumable work sessions"
```
### Task 2: Work-Session Model, Allowed Actions, and Secret-Safe Projection

**Files:**
- Create: `next/src/xp_next/work_session.py`
- Create: `next/tests/test_cp09b_work_session_service.py`

**Interfaces:**
- Consumes: `JobState`, StateStore job/session/activity rows.
- Produces:
  - `WorkAction`
  - `WorkSessionSnapshot`
  - `allowed_actions(state, payload)`
  - `public_session(snapshot)`

- [ ] **Step 1: Write RED contract tests**

```python
def test_ready_to_review_allows_only_apply_and_discard(self):
    payload = {
        "worker_confirmation": {"status": "CONFIRMED"},
        "sandbox_approved": True,
        "review": {"status": "PASS", "change_fingerprint": "abc"},
    }
    self.assertEqual(
        allowed_actions(JobState.READY_TO_REVIEW, payload),
        (WorkAction.APPLY, WorkAction.DISCARD),
    )

def test_projection_excludes_internal_fields(self):
    snapshot = WorkSessionSnapshot(
        job={"id": "j1", "project_id": "p1", "user_goal": "fix it",
             "state": "READY_TO_REVIEW"},
        session={
            "revision": 4,
            "payload": {
                "project_name": "Fixture",
                "worker_prompt": "PRIVATE_PROMPT",
                "sandbox_root": "/private/sandbox",
                "verifier": {"name": "verify", "argv": ["python", "-c", "SECRET"]},
                "review": {
                    "status": "PASS",
                    "changed_files": ["app.txt"],
                    "bounded_diff": "diff",
                    "change_fingerprint": "abc",
                },
            },
        },
        activities=(),
    )
    rendered = json.dumps(public_session(snapshot))
    self.assertNotIn("PRIVATE_PROMPT", rendered)
    self.assertNotIn("/private/sandbox", rendered)
    self.assertNotIn("SECRET", rendered)
    self.assertNotIn('"argv"', rendered)
```

- [ ] **Step 2: Run RED**

- [ ] **Step 3: Implement exact action/state rules**

```python
class WorkAction(str, Enum):
    CONFIRM_WORKER = "CONFIRM_WORKER"
    DECLINE_WORKER = "DECLINE_WORKER"
    APPROVE_SANDBOX = "APPROVE_SANDBOX"
    DECLINE_SANDBOX = "DECLINE_SANDBOX"
    EXECUTE = "EXECUTE"
    APPLY = "APPLY"
    DISCARD = "DISCARD"

def allowed_actions(
    state: JobState,
    payload: Mapping[str, object],
) -> tuple[WorkAction, ...]:
    if state is JobState.AWAITING_APPROVAL:
        confirmation = payload.get("worker_confirmation")
        if not isinstance(confirmation, dict):
            return (WorkAction.CONFIRM_WORKER, WorkAction.DECLINE_WORKER)
        if confirmation.get("status") != "CONFIRMED":
            return ()
        if payload.get("sandbox_approved") is None:
            return (WorkAction.APPROVE_SANDBOX, WorkAction.DECLINE_SANDBOX)
        if payload.get("sandbox_approved") is True:
            return (WorkAction.EXECUTE,)
        return ()
    if state is JobState.READY_TO_REVIEW:
        review = payload.get("review")
        if isinstance(review, dict) and review.get("status") == "PASS":
            return (WorkAction.APPLY, WorkAction.DISCARD)
    return ()
```

- [ ] **Step 4: Implement snapshot + public projection**

```python
@dataclass(frozen=True)
class WorkSessionSnapshot:
    job: dict[str, object]
    session: dict[str, object]
    activities: tuple[dict[str, object], ...]

    @property
    def state(self) -> JobState:
        return JobState(str(self.job["state"]))

    @property
    def revision(self) -> int:
        return int(self.session["revision"])

    @property
    def payload(self) -> dict[str, object]:
        value = self.session["payload"]
        if not isinstance(value, dict):
            raise ValueError("session payload must be an object")
        return value

    @property
    def allowed_actions(self) -> tuple[WorkAction, ...]:
        return allowed_actions(self.state, self.payload)
```

`public_session()` constructs a new dictionary from an allow-list. It does not copy the internal payload wholesale. Allowed browser fields are: id, project id/name, goal, state, display label, revision, visible worker recommendation/confirmation, sandbox approval state, review status/changed file names/bounded diff/fingerprint, final apply status, recovery availability, allowed actions, and projected activities.

- [ ] **Step 5: Add action-matrix tests**

Pin these cases: waiting worker; confirmed worker waiting sandbox; sandbox approved waiting execute; `READY_TO_REVIEW`; `NEEDS_ATTENTION`; `CANCELLED`; `COMPLETED`.

- [ ] **Step 6: Run Task 2 + full next regression**

- [ ] **Step 7: Commit**

```bash
git add next/src/xp_next/work_session.py   next/tests/test_cp09b_work_session_service.py
git commit -m "feat(xp-next): define visual work session contract"
```

### Task 3: Pause Existing Governed Execution at Review

**Files:**
- Modify: `next/src/xp_next/zero_cost_e2e.py`
- Create: `next/tests/test_cp09b_execution_phases.py`

**Interfaces:**
- Produces:
  - `PendingReviewResult`
  - `ZeroCostE2EService.execute_existing_to_review(*, job_id: str, project_id: str, goal: str, worker_prompt: str, verifier_specs: tuple[VerifierSpec, ...], worker_selection: WorkerSelection, worker_confirmation: WorkerConfirmation) -> PendingReviewResult | ZeroCostE2EResult`
  - `ZeroCostE2EService.finalize_existing_review(*, pending: PendingReviewResult, decision: HumanReviewDecision, verifier_specs: tuple[VerifierSpec, ...]) -> ZeroCostE2EResult`
- Existing `ZeroCostE2EService.run()` stays public and behavior-compatible.

- [ ] **Step 1: Write RED pause test**

Create the fixture job before execution, transition it through `PLANNING -> READY -> AWAITING_APPROVAL`, record worker/sandbox approvals, then:

```python
pending = service.execute_existing_to_review(
    job_id="cp09b-review",
    project_id="fixture",
    goal="change app.txt",
    worker_prompt=prompt,
    verifier_specs=(verifier,),
    worker_selection=selection,
    worker_confirmation=confirmation,
)
self.assertEqual(
    store.get_job("cp09b-review")["state"],
    JobState.READY_TO_REVIEW.value,
)
self.assertEqual(pending.review.status, ReviewStatus.PASS)
self.assertEqual((source / "app.txt").read_text(), "SAFE\n")
```

- [ ] **Step 2: Run RED**

- [ ] **Step 3: Add `PendingReviewResult`**

```python
@dataclass(frozen=True)
class PendingReviewResult:
    job_id: str
    project_id: str
    reasoning_status: str
    plan_status: str
    worker_status: str
    sandbox_root: str
    expected_original_head: str
    review: ReviewBundle
```

- [ ] **Step 4: Extract the existing reasoning→review body exactly once**

`execute_existing_to_review()` requires the existing job to be `AWAITING_APPROVAL`, then performs the current `run()` logic from readiness/reasoning through sandbox verification. It transitions `AWAITING_APPROVAL -> RUNNING -> VERIFYING -> READY_TO_REVIEW`. Preserve the existing:
- confirmed-backend identity check;
- local-Qwen and worker readiness gates;
- no-fallback behavior;
- isolated workspace creation;
- worker request containment;
- review/verifier checks;
- Activity Trail writes.

It stops before `HumanReviewDecision` and does not mutate the original project.

- [ ] **Step 5: Implement fresh finalize logic**

```python
def finalize_existing_review(
    self,
    *,
    pending: PendingReviewResult,
    decision: HumanReviewDecision,
    verifier_specs: tuple[VerifierSpec, ...],
) -> ZeroCostE2EResult:
    job = self.store.get_job(pending.job_id)
    if JobState(str(job["state"])) is not JobState.READY_TO_REVIEW:
        raise ValueError("job is not ready for review")

    fresh = build_review_bundle(
        pending.sandbox_root,
        verifier_specs=verifier_specs,
    )
    if fresh.status is not ReviewStatus.PASS:
        self.store.transition_job(pending.job_id, JobState.NEEDS_ATTENTION)
        return self._result(
            job_id=pending.job_id,
            reasoning_status=pending.reasoning_status,
            plan_status=pending.plan_status,
            worker_status=pending.worker_status,
            review_status=fresh.status.value,
            apply_status=None,
            sandbox_root=pending.sandbox_root,
            recovery_ref=None,
        )
    if decision.approved_change_fingerprint != fresh.change_fingerprint:
        self.store.transition_job(pending.job_id, JobState.NEEDS_ATTENTION)
        return self._result(
            job_id=pending.job_id,
            reasoning_status=pending.reasoning_status,
            plan_status=pending.plan_status,
            worker_status=pending.worker_status,
            review_status=fresh.status.value,
            apply_status=None,
            sandbox_root=pending.sandbox_root,
            recovery_ref=None,
        )
```

After those guards, reuse the existing Apply/Discard block unchanged, including `expected_original_head=pending.expected_original_head`, recovery recording, post-Apply verifier, rollback semantics, and final state transitions.

- [ ] **Step 6: Make existing `run()` a compatibility wrapper**

`run()` keeps its current public signature. It performs its current job creation/selection/approval bookkeeping, calls `execute_existing_to_review()`, invokes the supplied `review_decider`, then calls `finalize_existing_review()`. Existing CP-08 tests must not need call-site changes.

- [ ] **Step 7: Add original-HEAD drift test**

After `READY_TO_REVIEW`, modify and commit a separate change in the original fixture. Apply with the previously reviewed fingerprint. Assert Apply does not overwrite the new original HEAD and final result is not `APPLIED`.

- [ ] **Step 8: Add fingerprint mismatch test**

Pass `approved_change_fingerprint="stale"`. Assert original remains `SAFE\n` and job becomes `NEEDS_ATTENTION`.

- [ ] **Step 9: Run phase tests + full next regression**

- [ ] **Step 10: Commit**

```bash
git add next/src/xp_next/zero_cost_e2e.py   next/tests/test_cp09b_execution_phases.py
git commit -m "refactor(xp-next): pause governed execution at review"
```
### Task 4: Resumable WorkSessionService

**Files:**
- Create: `next/src/xp_next/work_session_service.py`
- Modify: `next/tests/test_cp09b_work_session_service.py`

**Interfaces:**
- Consumes Task 1 store methods, Task 2 models, Task 3 execution phases, `prepare_work()`, `WorkerSelector`, `confirm_worker_selection()`.
- Produces:
  - `create(*, job_id: str, project_id: str | None, goal: str, worker_prompt: str | None = None, verifier_command: str | None = None, verifier_timeout: float = 120.0, requested_backend: str | None = None) -> WorkSessionSnapshot`
  - `get(job_id: str) -> WorkSessionSnapshot`
  - `decide_worker(job_id: str, *, backend_id: str, approved: bool, expected_revision: int) -> WorkSessionSnapshot`
  - `decide_sandbox(job_id: str, *, approved: bool, expected_revision: int) -> WorkSessionSnapshot`
  - `execute(job_id: str, *, expected_revision: int) -> WorkSessionSnapshot`
  - `decide_review(job_id: str, *, action: ReviewAction, fingerprint: str, expected_revision: int) -> WorkSessionSnapshot`

- [ ] **Step 1: Write RED create-session test**

```python
snapshot = service.create(
    job_id="visual-1",
    project_id="fixture",
    goal="replace SAFE with CHANGED",
    worker_prompt=prompt,
    verifier_command=(
        "python -c \"from pathlib import Path; "
        "assert Path('app.txt').read_text() == 'CHANGED\\n'\""
    ),
)
self.assertEqual(snapshot.state, JobState.AWAITING_APPROVAL)
self.assertEqual(
    snapshot.payload["worker_selection"]["backend_id"],
    "lightweight_local",
)
self.assertEqual(
    snapshot.allowed_actions,
    (WorkAction.CONFIRM_WORKER, WorkAction.DECLINE_WORKER),
)
```

- [ ] **Step 2: Run RED**

- [ ] **Step 3: Implement constructor and snapshot loader**

```python
class WorkSessionService:
    def __init__(
        self,
        *,
        store: StateStore,
        projects: ProjectService,
        paths: RuntimePaths,
        reasoner: object,
        planner: BoundedReadOnlyPlanner,
        workers: Mapping[str, object],
        selector: WorkerSelector,
        resource_probe: Callable[[], ResourceSnapshot] = ResourceSnapshot.probe_local_linux,
    ):
        self.store = store
        self.projects = projects
        self.paths = paths
        self.reasoner = reasoner
        self.planner = planner
        self.workers = dict(workers)
        self.selector = selector
        self.resource_probe = resource_probe

    def get(self, job_id: str) -> WorkSessionSnapshot:
        job = self.store.get_job(job_id)
        session = self.store.get_work_session(job_id)
        activities = tuple(self.store.list_activities(job_id))
        return WorkSessionSnapshot(job, session, activities)
```

- [ ] **Step 4: Implement create/prepare/recommend**

Tests construct the service with `resource_probe=lambda: ResourceSnapshot(available_memory_mb=512, logical_cpus=2)`. Production code calls `self.resource_probe()`; the gateway never accepts CPU/memory values from browser JSON.

Exact sequence:
1. `prepare_work()`;
2. `store.create_job(job_id, prepared.project_id, prepared.goal, risk="write")`;
3. transition `DRAFT -> PLANNING`;
4. create `WorkerSelectionRequest(worker_prompt=prepared.worker_prompt, requested_backend=requested_backend)`;
5. `selector.select(request, resources=self.resource_probe())`;
6. persist internal prepared/verifier/prompt/selection data;
7. selection failure → `NEEDS_ATTENTION`;
8. otherwise transition `PLANNING -> READY -> AWAITING_APPROVAL`.

Persist verifier internally as:
```python
{
    "name": prepared.verifier.name,
    "argv": list(prepared.verifier.argv),
    "timeout_seconds": prepared.verifier.timeout_seconds,
}
```
but never emit `argv` from `public_session()`.

- [ ] **Step 5: Implement worker decision**

```python
confirmation = confirm_worker_selection(
    self.selector,
    selection=selection,
    request=request,
    confirmation=HumanWorkerConfirmation(
        backend_id=backend_id,
        approved=approved,
    ),
    resources=self.resource_probe(),
)
self.store.record_approval(
    f"{job_id}:approval:worker",
    job_id=job_id,
    approval_class="worker_selection",
    granted=confirmation.status is ConfirmationStatus.CONFIRMED,
)
```

Decline → `CANCELLED`; mismatch/readiness loss → `NEEDS_ATTENTION`; confirmed → persist confirmation and stay `AWAITING_APPROVAL`.

- [ ] **Step 6: Implement sandbox decision without executing**

For approval, record `approval_class="sandbox_write"`, persist `sandbox_approved=True`, keep state `AWAITING_APPROVAL`, and expose only `EXECUTE`. Decline records false and transitions to `CANCELLED`.

- [ ] **Step 7: Implement execute-to-review**

Require matching `expected_revision`, confirmed worker, and sandbox approval. Reconstruct `VerifierSpec` from internal payload. Bind exactly the confirmed worker:

```python
backend_id = str(payload["worker_confirmation"]["backend_id"])
worker = self.workers.get(backend_id)
if worker is None:
    self.store.transition_job(job_id, JobState.NEEDS_ATTENTION)
    raise ValueError("confirmed worker is unavailable; no fallback")
```

Create `ZeroCostE2EService` with that worker, call `execute_existing_to_review()` with the persisted job/project/goal/prompt/verifier/selection/confirmation, then persist review status/files/diff/fingerprint, expected source HEAD, and internal sandbox path using `self.store.update_work_session(job_id, payload, expected_revision=expected_revision)`.

- [ ] **Step 8: Implement review resume**

Reconstruct `PendingReviewResult` from durable session state; do not rerun the worker. Require the browser-supplied fingerprint to equal the persisted reviewed fingerprint before calling the engine. Then call `finalize_existing_review()` with `ReviewAction.APPLY` or `DISCARD`.

- [ ] **Step 9: Add restart test**

Execute to `READY_TO_REVIEW`, close StateStore/runtime, reopen the same home, reconstruct `WorkSessionService`, load the session, and Discard. Assert worker run count remains 1.

- [ ] **Step 10: Add corrupt/missing sandbox test**

Remove the sandbox directory after review. Reopen and request Apply. Assert the service catches the missing review source, transitions to `NEEDS_ATTENTION`, and original source remains unchanged.

- [ ] **Step 11: Add stale-revision tests for worker, sandbox, execute, and review decisions**

Use the same old revision twice. First call succeeds; second raises `StateStoreError("work session revision changed; refresh state")`. Count approvals/worker runs to prove no duplicate side effect.

- [ ] **Step 12: Run Task 4 + full next regression and commit**

```bash
git add next/src/xp_next/work_session_service.py   next/tests/test_cp09b_work_session_service.py
git commit -m "feat(xp-next): add resumable governed work session service"
```

### Task 5: Bounded Project, Snapshot, and Activity Views

**Files:**
- Modify: `next/src/xp_next/work_session_service.py`
- Modify: `next/tests/test_cp09b_work_session_service.py`

**Interfaces:**
- Produces:
  - `list_visual_projects()`
  - `select_visual_project(project_id)`
  - `visual_snapshot()`
  - `public_activity(job_id=None, limit=50)`

- [ ] **Step 1: Write RED projection tests**

```python
projects = service.list_visual_projects()
self.assertEqual(projects[0]["id"], "fixture")
self.assertIn("name", projects[0])
self.assertIn("active", projects[0])
self.assertIn("git", projects[0])
self.assertNotIn("files", projects[0])

events = service.public_activity("visual-1", limit=50)
rendered = json.dumps(events)
self.assertNotIn("worker_prompt", rendered)
self.assertNotIn("chain_of_thought", rendered)
self.assertLessEqual(len(events), 50)
```

- [ ] **Step 2: Implement project allow-list and selection**

`list_visual_projects()` returns the bounded projection below. `select_visual_project(project_id)` calls `self.projects.switch(project_id)`, then returns the same bounded projection for the newly active project; it never mutates files or Git.

For each registered project emit:
```python
{
    "id": project["id"],
    "name": project["name"],
    "source_kind": project["source_kind"],
    "active": bool(project["active"]),
    "git": {
        "inside_work_tree": inspection["git"]["inside_work_tree"],
        "dirty": inspection["git"]["dirty"],
        "branch": inspection["git"].get("branch"),
        "head": str(inspection["git"].get("head") or "")[:12],
    },
}
```

- [ ] **Step 3: Implement visual snapshot**

Return product/version, active project summary, `LocalCapabilityRegistry().snapshot()`, the first row from `self.store.list_work_sessions(limit=1)` projected through `public_session(self.get(job_id))` when one exists, and recovery-point count. Construct a new dict; do not dump DB rows wholesale.

- [ ] **Step 4: Implement bounded activity projection**

```python
return [
    {
        "action": row["action"],
        "status": row["status"],
        "summary": row["summary"],
        "source": row["source"],
        "processor": row["processor"],
        "live": bool(row["live"]),
        "created_at": row["created_at"],
    }
    for row in rows[-limit:]
]
```

Reject `limit < 1`; clamp `limit > 50` to 50.

- [ ] **Step 5: Run tests and commit**

```bash
git add next/src/xp_next/work_session_service.py   next/tests/test_cp09b_work_session_service.py
git commit -m "feat(xp-next): expose bounded visual projections"
```
### Task 6: Same-Origin Loopback Visual Gateway

**Files:**
- Create: `next/src/xp_next/visual_gateway.py`
- Modify: `next/src/xp_next/cli.py`
- Create: `next/tests/test_cp09b_visual_gateway.py`

**Interfaces:**
- Consumes: `WorkSessionService`.
- Produces: `make_visual_gateway(host, port, service, static_root=None)` and `xp-next visual-gateway`.

- [ ] **Step 1: Write RED bind/security tests**

```python
with self.assertRaises(ValueError):
    make_visual_gateway(
        host="0.0.0.0",
        port=0,
        service=service,
    )
```

Start a loopback server and assert mutation requests return 403 when cookie or Origin is absent, and 415 when content type is not JSON.

- [ ] **Step 2: Write RED route tests**

Pin:
- `GET /api/v2/snapshot`;
- `GET /api/v2/projects`;
- `POST /api/v2/projects/select`;
- `POST /api/v2/work-sessions`;
- `GET /api/v2/work-sessions/{id}`;
- worker/sandbox/execute/review decision POSTs;
- unknown path → 404 JSON.

- [ ] **Step 3: Implement loopback host and same-origin checks**

```python
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

def _validate_bind_host(host: str) -> None:
    if host not in _LOOPBACK_HOSTS:
        raise ValueError("visual gateway must bind to loopback only")

def _expected_origin(host: str, port: int) -> str:
    display = f"[{host}]" if ":" in host else host
    return f"http://{display}:{port}"
```

At server creation generate `session_nonce = secrets.token_urlsafe(32)`.

GET `/` or static index sends:
```text
Set-Cookie: xp_session=<nonce>; HttpOnly; SameSite=Strict; Path=/
```

Mutation preflight requires:
- valid loopback `Host`;
- exact `Origin == expected_origin`;
- exact session cookie value;
- `Content-Type` beginning with `application/json`.

No `Access-Control-Allow-Origin: *` header is emitted.

- [ ] **Step 4: Implement bounded JSON response**

```python
def _send_json(self, status: int, payload: dict[str, object]) -> None:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    self.send_response(status)
    self.send_header("Content-Type", "application/json; charset=utf-8")
    self.send_header("Content-Length", str(len(body)))
    self.send_header("Cache-Control", "no-store")
    self.send_header("X-Content-Type-Options", "nosniff")
    self.end_headers()
    self.wfile.write(body)
```

500 responses are `{"ok": false, "error": "internal gateway error"}`; Python exception text/tracebacks stay server-side only.

- [ ] **Step 5: Implement exact route-to-service mapping**

```text
GET  /api/v2/snapshot
     -> service.visual_snapshot()

GET  /api/v2/projects
     -> service.list_visual_projects()

POST /api/v2/projects/select
     -> service.select_visual_project(project_id)

POST /api/v2/work-sessions
     -> service.create(...)

GET  /api/v2/work-sessions/{id}
     -> public_session(service.get(id))

POST /api/v2/work-sessions/{id}/worker-decision
     -> service.decide_worker(... expected_revision)

POST /api/v2/work-sessions/{id}/sandbox-decision
     -> service.decide_sandbox(... expected_revision)

POST /api/v2/work-sessions/{id}/execute
     -> service.execute(... expected_revision)

POST /api/v2/work-sessions/{id}/review-decision
     -> service.decide_review(... expected_revision)
```

Map stale revision/invalid state to 409, malformed JSON to 400, auth/origin to 403, wrong content type to 415, missing job/project to 404.

- [ ] **Step 6: Add retry/idempotency test**

Send the same `execute` or review POST twice with the same `expected_revision`. Assert first succeeds, second returns 409, and fake service call count remains 1 for the side effect.

- [ ] **Step 7: Add explicit development CLI command and dependency wiring**

In `cli.py`, factor the existing worker construction into a shared helper:

```python
def _build_local_workers(args: argparse.Namespace) -> dict[str, object]:
    return {
        "lightweight_local": LightweightLocalWorker(),
        "hermes": HermesLocalWorker(
            binary=getattr(args, "hermes_binary", None),
            base_url=getattr(args, "hermes_base_url", "http://127.0.0.1:18085/v1"),
            model=getattr(args, "hermes_model", "local"),
        ),
    }
```

Use that helper in the existing worker/work commands and in the new visual-gateway command so backend definitions do not diverge. The gateway command opens `XPRuntime`, creates `ProjectService`, `LocalQwenAdapter`, `BoundedReadOnlyPlanner`, `WorkerSelector`, and `WorkSessionService`, then passes the service to `make_visual_gateway()`.

In `cli.py` add:
```text
xp-next visual-gateway --host 127.0.0.1 --port 8765
```

Default host is `127.0.0.1`; passing `0.0.0.0` is rejected by `make_visual_gateway`. This is only a CP-09B developer entry point; it does not replace final `xp`.

- [ ] **Step 8: Run gateway tests + AF-10 regression**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/next/src" python3 -m unittest next.tests.test_cp09b_visual_gateway -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" python3 -m unittest tests.test_af10_visual_workstation -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" python3 scripts/xp_visual.py --self-test
```

- [ ] **Step 9: Commit**

```bash
git add next/src/xp_next/visual_gateway.py next/src/xp_next/cli.py   next/tests/test_cp09b_visual_gateway.py
git commit -m "feat(xp-next): expose governed loopback visual gateway"
```

### Task 7: HTTP End-to-End Acceptance and Safe Checkpoint

**Files:**
- Create: `next/tests/test_cp09b_e2e.py`
- Create: `docs/xp-next/CP09B_PWA_XP_NEXT_CONVERGENCE.md`

**Interfaces:**
- Consumes complete session service + visual gateway.
- Produces fixture-backed acceptance evidence and safe checkpoint.

- [ ] **Step 1: Implement exact isolated Git fixture**

```python
def init_source(root: Path) -> None:
    root.mkdir()
    (root / "app.txt").write_text("SAFE\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email",
         "cp09b@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "CP09B Fixture"],
        check=True,
    )
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-qm", "fixture baseline"],
        check=True,
    )

def lightweight_prompt() -> str:
    return json.dumps({
        "operation": "replace_text",
        "path": "app.txt",
        "expected_text": "SAFE\n",
        "new_text": "CHANGED\n",
    })
```

Use the existing loopback reasoning fixture pattern from CP-08 tests. Verifier:
```python
VerifierSpec(
    name="content-check",
    argv=(
        sys.executable,
        "-c",
        "from pathlib import Path; "
        "assert Path('app.txt').read_text() == 'CHANGED\\n'",
    ),
)
```

- [ ] **Step 2: Test complete Discard through HTTP**

Open `/` to receive cookie, use exact same-origin `Origin`, then:
create → confirm worker → approve sandbox → execute → assert `READY_TO_REVIEW` and original still `SAFE\n` → review `DISCARD` → assert state `CANCELLED`, apply status `DISCARDED`, original still `SAFE\n`.

- [ ] **Step 3: Test complete Apply through HTTP**

New fixture/session: same path through review, send the exact returned fingerprint with `APPLY`; assert state `COMPLETED`, apply status `APPLIED`, original `CHANGED\n`, post-Apply verifier PASS, and recovery reference exists.

- [ ] **Step 4: Test gateway/runtime restart at review**

Stop gateway at `READY_TO_REVIEW`, close runtime, reopen the same runtime home, recreate service/gateway, GET the same session, then Discard. Worker fake/run counter must remain 1 and session revision must increase rather than reset.

- [ ] **Step 5: Test all critical failure classes**

Add separate tests for:
- dirty original at create → blocked, no job execution;
- worker declined → `CANCELLED`;
- sandbox declined → `CANCELLED`;
- failing verifier → `NEEDS_ATTENTION`, no Apply action;
- wrong review fingerprint → no original mutation;
- original HEAD drift → no overwrite;
- deleted sandbox after review → `NEEDS_ATTENTION`;
- stale revision → HTTP 409, no repeated side effect;
- invalid Origin or cookie → HTTP 403.

- [ ] **Step 6: Run dedicated CP-09B suite**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/next/src" python3 -m unittest   next.tests.test_cp09b_session_store   next.tests.test_cp09b_execution_phases   next.tests.test_cp09b_work_session_service   next.tests.test_cp09b_visual_gateway   next.tests.test_cp09b_e2e -v
```

- [ ] **Step 7: Run full XP Next regression and record fresh total**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/next/src" python3 -m unittest discover -s next/tests -q
```

Do not assume the old 142 count; record the actual fresh total.

- [ ] **Step 8: Run AF-10/PWA regression**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" python3 -m unittest tests.test_af10_visual_workstation -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" python3 scripts/xp_visual.py --self-test
```

- [ ] **Step 9: Run hygiene gates**

```bash
git diff --check
git status --short --branch
```

Only intentional CP-09B files may be dirty.

- [ ] **Step 10: Write evidence report**

`docs/xp-next/CP09B_PWA_XP_NEXT_CONVERGENCE.md` records baseline/final SHA, exact fresh test counts, Discard/Apply/restart results, loopback and same-origin protection, stale revision/source HEAD/fingerprint guards, AF-10 results, Segeran Jiwa untouched, production DB untouched, deploy none, and CP-09C as the visual UX follow-up.

- [ ] **Step 11: Commit, push, and remote-verify**

```bash
git add next/src/xp_next next/tests   docs/xp-next/CP09B_PWA_XP_NEXT_CONVERGENCE.md
git commit -m "feat(xp-next): complete CP09B PWA engine convergence"
git push origin planning/xp-next-bootstrap
git fetch origin --prune
test "$(git rev-parse HEAD)" =      "$(git rev-parse origin/planning/xp-next-bootstrap)"
git status --short --branch
```

## Final Acceptance Gate

Do not report CP-09B complete without fresh evidence for every line:

```text
CP-09B SAFE CHECKPOINT
REMOTE VERIFIED       : YES
DEDICATED CP09B TESTS : PASS
XP NEXT REGRESSION    : PASS (fresh exact count)
AF-10 VISUAL TESTS    : PASS
PWA SELF-TEST         : PASS
DISCARD E2E           : PASS
APPLY E2E             : PASS
RESTART/RESUME        : PASS
STALE REQUEST GUARD   : PASS
SOURCE HEAD GUARD     : PASS
FINGERPRINT GUARD     : PASS
WORKTREE              : CLEAN
SEG. JIWA             : UNTOUCHED
PRODUCTION DB         : UNTOUCHED
DEPLOY                 : NONE
```
