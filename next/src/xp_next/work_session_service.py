from __future__ import annotations

from copy import deepcopy
from typing import Callable, Mapping

from .capability_registry import LocalCapabilityRegistry
from .job_state import JobState
from .planner import BoundedReadOnlyPlanner
from .project_service import ProjectService
from .runtime_paths import RuntimePaths
from .sandbox_review import (
    ReviewBundle,
    ReviewStatus,
    VerifierResult,
    VerifierSpec,
)
from .state_store import StateStore, StateStoreError
from .work_flow import prepare_work
from .work_session import WorkAction, WorkSessionSnapshot, public_session
from .worker_selection import (
    ConfirmationStatus,
    HumanWorkerConfirmation,
    ResourceSnapshot,
    SelectionStatus,
    WorkerConfirmation,
    WorkerSelection,
    WorkerSelectionRequest,
    WorkerSelector,
    confirm_worker_selection,
)
from .zero_cost_e2e import (
    HumanReviewDecision,
    PendingReviewResult,
    ReviewAction,
    ZeroCostE2EResult,
    ZeroCostE2EService,
)


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
        return WorkSessionSnapshot(
            job=job,
            session=session,
            activities=activities,
        )

    @staticmethod
    def _require_revision(
        snapshot: WorkSessionSnapshot,
        expected_revision: int,
    ) -> None:
        if snapshot.revision != expected_revision:
            raise StateStoreError(
                "work session revision changed; refresh state"
            )

    @staticmethod
    def _require_action(
        snapshot: WorkSessionSnapshot,
        action: WorkAction,
    ) -> None:
        if action not in snapshot.allowed_actions:
            raise StateStoreError(
                f"action {action.value} is not allowed in state "
                f"{snapshot.state.value}"
            )

    @staticmethod
    def _selection_from_payload(
        payload: Mapping[str, object],
    ) -> WorkerSelection:
        raw = payload.get("worker_selection")
        if not isinstance(raw, Mapping):
            raise StateStoreError("worker selection is missing")
        resources_raw = raw.get("resource_snapshot")
        if not isinstance(resources_raw, Mapping):
            raise StateStoreError("worker selection resource snapshot is missing")
        resources = ResourceSnapshot(
            available_memory_mb=int(resources_raw["available_memory_mb"]),
            logical_cpus=int(resources_raw["logical_cpus"]),
            source=str(resources_raw.get("source") or "persisted"),
        )
        considered = raw.get("considered_backends")
        if not isinstance(considered, (list, tuple)):
            raise StateStoreError("worker selection considered_backends is invalid")
        return WorkerSelection(
            status=SelectionStatus(str(raw["status"])),
            backend_id=(
                None
                if raw.get("backend_id") is None
                else str(raw["backend_id"])
            ),
            detail=str(raw.get("detail") or ""),
            explicit=bool(raw.get("explicit")),
            requires_confirmation=bool(raw.get("requires_confirmation")),
            considered_backends=tuple(str(item) for item in considered),
            resource_snapshot=resources,
        )

    @staticmethod
    def _confirmation_from_payload(
        payload: Mapping[str, object],
    ) -> WorkerConfirmation:
        raw = payload.get("worker_confirmation")
        if not isinstance(raw, Mapping):
            raise StateStoreError("worker confirmation is missing")
        resources_raw = raw.get("resource_snapshot")
        if not isinstance(resources_raw, Mapping):
            raise StateStoreError("worker confirmation resource snapshot is missing")
        return WorkerConfirmation(
            status=ConfirmationStatus(str(raw["status"])),
            backend_id=(
                None
                if raw.get("backend_id") is None
                else str(raw["backend_id"])
            ),
            detail=str(raw.get("detail") or ""),
            resource_snapshot=ResourceSnapshot(
                available_memory_mb=int(resources_raw["available_memory_mb"]),
                logical_cpus=int(resources_raw["logical_cpus"]),
                source=str(resources_raw.get("source") or "persisted"),
            ),
            selection_status=SelectionStatus(
                str(raw["selection_status"])
            ),
        )

    @staticmethod
    def _verifier_from_payload(
        payload: Mapping[str, object],
    ) -> VerifierSpec:
        raw = payload.get("verifier")
        if not isinstance(raw, Mapping):
            raise StateStoreError("verifier configuration is missing")
        argv = raw.get("argv")
        if not isinstance(argv, (list, tuple)):
            raise StateStoreError("verifier argv is missing")
        return VerifierSpec(
            name=str(raw["name"]),
            argv=tuple(str(item) for item in argv),
            timeout_seconds=float(raw["timeout_seconds"]),
        )

    @staticmethod
    def _review_from_payload(
        payload: Mapping[str, object],
    ) -> ReviewBundle:
        raw = payload.get("review")
        if not isinstance(raw, Mapping):
            raise StateStoreError("review payload is missing")
        verifier_rows = raw.get("verifiers")
        if not isinstance(verifier_rows, (list, tuple)):
            raise StateStoreError("review verifier results are missing")
        verifiers: list[VerifierResult] = []
        for item in verifier_rows:
            if not isinstance(item, Mapping):
                raise StateStoreError("review verifier result is invalid")
            verifiers.append(
                VerifierResult(
                    name=str(item["name"]),
                    status=ReviewStatus(str(item["status"])),
                    returncode=(
                        None
                        if item.get("returncode") is None
                        else int(item["returncode"])
                    ),
                    output=str(item.get("output") or ""),
                    detail=str(item.get("detail") or ""),
                )
            )
        changed = raw.get("changed_files")
        if not isinstance(changed, (list, tuple)):
            raise StateStoreError("review changed_files is invalid")
        return ReviewBundle(
            status=ReviewStatus(str(raw["status"])),
            summary=str(raw.get("summary") or ""),
            changed_files=tuple(str(item) for item in changed),
            bounded_diff=str(raw.get("bounded_diff") or ""),
            diff_truncated=bool(raw.get("diff_truncated")),
            verifiers=tuple(verifiers),
            sandbox_head=str(raw.get("sandbox_head") or ""),
            change_fingerprint=str(raw.get("change_fingerprint") or ""),
            verifier_spec_fingerprint=str(
                raw.get("verifier_spec_fingerprint") or ""
            ),
            apply_to_original_performed=bool(
                raw.get("apply_to_original_performed", False)
            ),
        )

    def create(
        self,
        *,
        job_id: str,
        project_id: str | None,
        goal: str,
        worker_prompt: str | None = None,
        verifier_command: str | None = None,
        verifier_timeout: float = 120.0,
        requested_backend: str | None = None,
    ) -> WorkSessionSnapshot:
        prepared = prepare_work(
            self.projects,
            goal=goal,
            project_id=project_id,
            worker_prompt=worker_prompt,
            verifier_command=verifier_command,
            verifier_timeout=verifier_timeout,
        )
        self.store.create_job(
            job_id,
            prepared.project_id,
            prepared.goal,
            risk="write",
        )
        self.store.transition_job(job_id, JobState.PLANNING)

        request = WorkerSelectionRequest(
            worker_prompt=prepared.worker_prompt,
            requested_backend=requested_backend,
        )
        selection = self.selector.select(
            request,
            resources=self.resource_probe(),
        )
        payload: dict[str, object] = {
            "project_name": prepared.project_name,
            "project_root": prepared.project_root,
            "source_head": prepared.source_head,
            "worker_prompt": prepared.worker_prompt,
            "requested_backend": requested_backend,
            "verifier": {
                "name": prepared.verifier.name,
                "argv": list(prepared.verifier.argv),
                "timeout_seconds": prepared.verifier.timeout_seconds,
            },
            "verifier_source": prepared.verifier_source,
            "worker_selection": selection.as_dict(),
            "sandbox_approved": None,
            "review": None,
            "apply_status": None,
            "recovery_ref": None,
        }
        self.store.create_work_session(job_id, payload)

        resources = selection.resource_snapshot
        self.store.record_activity(
            f"{job_id}:activity:worker-selection",
            job_id=job_id,
            category="worker_selection",
            action="recommend_worker",
            status=(
                "Selesai"
                if selection.backend_id is not None
                else "Perlu perhatian"
            ),
            summary=(
                f"{selection.status.value}: backend="
                f"{selection.backend_id or 'none'}; {selection.detail}; "
                f"memory_mb={resources.available_memory_mb}; "
                f"logical_cpus={resources.logical_cpus}"
            ),
            source="local_resource_and_capability_policy",
            processor="xp_next_worker_selector",
            live=False,
        )

        if selection.status is SelectionStatus.NEEDS_ATTENTION:
            self.store.transition_job(job_id, JobState.NEEDS_ATTENTION)
            return self.get(job_id)

        self.store.transition_job(job_id, JobState.READY)
        self.store.transition_job(job_id, JobState.AWAITING_APPROVAL)
        return self.get(job_id)

    def decide_worker(
        self,
        job_id: str,
        *,
        backend_id: str,
        approved: bool,
        expected_revision: int,
    ) -> WorkSessionSnapshot:
        snapshot = self.get(job_id)
        self._require_revision(snapshot, expected_revision)
        self._require_action(
            snapshot,
            (
                WorkAction.CONFIRM_WORKER
                if approved
                else WorkAction.DECLINE_WORKER
            ),
        )
        payload = deepcopy(snapshot.payload)
        selection = self._selection_from_payload(payload)
        request = WorkerSelectionRequest(
            worker_prompt=str(payload["worker_prompt"]),
            requested_backend=(
                None
                if payload.get("requested_backend") is None
                else str(payload["requested_backend"])
            ),
        )
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
        self.store.record_activity(
            f"{job_id}:activity:worker-confirmation",
            job_id=job_id,
            category="approval",
            action="confirm_worker",
            status=(
                "Selesai"
                if confirmation.status is ConfirmationStatus.CONFIRMED
                else (
                    "Gagal"
                    if confirmation.status is ConfirmationStatus.DECLINED
                    else "Perlu perhatian"
                )
            ),
            summary=confirmation.detail,
            source="human",
            processor="xp_next_worker_selector",
            live=False,
        )

        payload["worker_confirmation"] = confirmation.as_dict()
        self.store.update_work_session(
            job_id,
            payload,
            expected_revision=expected_revision,
        )
        if confirmation.status is ConfirmationStatus.DECLINED:
            self.store.transition_job(job_id, JobState.CANCELLED)
        elif confirmation.status is ConfirmationStatus.NEEDS_ATTENTION:
            self.store.transition_job(job_id, JobState.NEEDS_ATTENTION)
        return self.get(job_id)

    def decide_sandbox(
        self,
        job_id: str,
        *,
        approved: bool,
        expected_revision: int,
    ) -> WorkSessionSnapshot:
        snapshot = self.get(job_id)
        self._require_revision(snapshot, expected_revision)
        self._require_action(
            snapshot,
            (
                WorkAction.APPROVE_SANDBOX
                if approved
                else WorkAction.DECLINE_SANDBOX
            ),
        )
        payload = deepcopy(snapshot.payload)
        self.store.record_approval(
            f"{job_id}:approval:sandbox",
            job_id=job_id,
            approval_class="sandbox_write",
            granted=approved,
        )
        self.store.record_activity(
            f"{job_id}:activity:sandbox-approval",
            job_id=job_id,
            category="approval",
            action="sandbox_write",
            status="Selesai" if approved else "Gagal",
            summary="Explicit human decision recorded for isolated sandbox write.",
            source="human",
            live=False,
        )
        payload["sandbox_approved"] = approved
        self.store.update_work_session(
            job_id,
            payload,
            expected_revision=expected_revision,
        )
        if not approved:
            self.store.transition_job(job_id, JobState.CANCELLED)
        return self.get(job_id)

    def execute(
        self,
        job_id: str,
        *,
        expected_revision: int,
    ) -> WorkSessionSnapshot:
        snapshot = self.get(job_id)
        self._require_revision(snapshot, expected_revision)
        self._require_action(snapshot, WorkAction.EXECUTE)
        payload = deepcopy(snapshot.payload)

        selection = self._selection_from_payload(payload)
        confirmation = self._confirmation_from_payload(payload)
        if confirmation.backend_id is None:
            self.store.transition_job(job_id, JobState.NEEDS_ATTENTION)
            raise StateStoreError("confirmed worker backend is missing")
        worker = self.workers.get(confirmation.backend_id)
        if worker is None:
            self.store.transition_job(job_id, JobState.NEEDS_ATTENTION)
            raise StateStoreError(
                "confirmed worker is unavailable; no fallback"
            )

        verifier = self._verifier_from_payload(payload)
        engine = ZeroCostE2EService(
            store=self.store,
            projects=self.projects,
            paths=self.paths,
            reasoner=self.reasoner,
            planner=self.planner,
            worker=worker,
        )
        result = engine.execute_existing_to_review(
            job_id=job_id,
            project_id=str(snapshot.job["project_id"]),
            goal=str(snapshot.job["user_goal"]),
            worker_prompt=str(payload["worker_prompt"]),
            verifier_specs=(verifier,),
            worker_selection=selection,
            worker_confirmation=confirmation,
        )

        if isinstance(result, ZeroCostE2EResult):
            payload["execution_result"] = result.as_dict()
            payload["apply_status"] = result.apply_status
            payload["recovery_ref"] = result.recovery_ref
        else:
            payload["sandbox_root"] = result.sandbox_root
            payload["expected_original_head"] = result.expected_original_head
            payload["review"] = result.review.as_dict()
            payload["execution"] = {
                "reasoning_status": result.reasoning_status,
                "plan_status": result.plan_status,
                "worker_status": result.worker_status,
            }

        self.store.update_work_session(
            job_id,
            payload,
            expected_revision=expected_revision,
        )
        return self.get(job_id)


    def _visual_project(
        self,
        project: Mapping[str, object],
    ) -> dict[str, object]:
        inspection = self.projects.inspect(str(project["id"]))
        git_raw = inspection.get("git")
        git = git_raw if isinstance(git_raw, Mapping) else {}
        return {
            "id": project["id"],
            "name": project["name"],
            "source_kind": project["source_kind"],
            "active": bool(project["active"]),
            "git": {
                "inside_work_tree": git.get("inside_work_tree"),
                "dirty": git.get("dirty"),
                "branch": git.get("branch"),
                "head": str(git.get("head") or "")[:12],
            },
        }

    def list_visual_projects(self) -> list[dict[str, object]]:
        return [
            self._visual_project(project)
            for project in self.projects.list_projects()
        ]

    def select_visual_project(
        self,
        project_id: str,
    ) -> dict[str, object]:
        project = self.projects.switch(project_id)
        return self._visual_project(project)

    def visual_snapshot(self) -> dict[str, object]:
        active = self.projects.current()
        latest_rows = self.store.list_work_sessions(limit=1)
        latest_session: dict[str, object] | None = None
        if latest_rows:
            latest_session = public_session(
                self.get(str(latest_rows[0]["job_id"]))
            )

        capabilities_raw = LocalCapabilityRegistry().snapshot()
        capabilities = {
            name: {
                "state": value.get("state"),
                "version": value.get("version"),
                "network_used": bool(value.get("network_used", False)),
            }
            for name, value in capabilities_raw.items()
        }

        return {
            "product": "XP Next",
            "active_project": (
                None if active is None else self._visual_project(active)
            ),
            "capabilities": capabilities,
            "latest_session": latest_session,
            "recovery_count": len(self.store.list_recovery_points()),
        }

    def public_activity(
        self,
        job_id: str | None = None,
        *,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        if limit < 1:
            raise ValueError("limit must be positive")
        bounded = min(limit, 50)

        if job_id is not None:
            rows = self.store.list_activities(job_id)[-bounded:]
        else:
            fetched = self.store.connection.execute(
                """
                SELECT * FROM activities
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (bounded,),
            ).fetchall()
            rows = [
                {key: row[key] for key in row.keys()}
                for row in reversed(fetched)
            ]

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
            for row in rows
        ]

    def decide_review(
        self,
        job_id: str,
        *,
        action: ReviewAction,
        fingerprint: str,
        expected_revision: int,
    ) -> WorkSessionSnapshot:
        snapshot = self.get(job_id)
        self._require_revision(snapshot, expected_revision)
        required = (
            WorkAction.APPLY
            if action is ReviewAction.APPLY
            else WorkAction.DISCARD
        )
        self._require_action(snapshot, required)
        payload = deepcopy(snapshot.payload)

        review_raw = payload.get("review")
        if not isinstance(review_raw, Mapping):
            raise StateStoreError("review payload is missing")
        reviewed_fingerprint = str(
            review_raw.get("change_fingerprint") or ""
        )
        if not fingerprint.strip() or fingerprint != reviewed_fingerprint:
            self.store.transition_job(job_id, JobState.NEEDS_ATTENTION)
            payload["review_error"] = "fingerprint_mismatch"
            self.store.update_work_session(
                job_id,
                payload,
                expected_revision=expected_revision,
            )
            return self.get(job_id)

        execution = payload.get("execution")
        if not isinstance(execution, Mapping):
            raise StateStoreError("execution state is missing")
        sandbox_root = str(payload.get("sandbox_root") or "")
        expected_head = str(payload.get("expected_original_head") or "")
        if not sandbox_root or not expected_head:
            self.store.transition_job(job_id, JobState.NEEDS_ATTENTION)
            payload["review_error"] = "review_resume_metadata_missing"
            self.store.update_work_session(
                job_id,
                payload,
                expected_revision=expected_revision,
            )
            return self.get(job_id)

        verifier = self._verifier_from_payload(payload)
        review = self._review_from_payload(payload)
        confirmation = self._confirmation_from_payload(payload)
        if confirmation.backend_id is None:
            raise StateStoreError("confirmed worker backend is missing")
        worker = self.workers.get(confirmation.backend_id)
        if worker is None:
            self.store.transition_job(job_id, JobState.NEEDS_ATTENTION)
            payload["review_error"] = "confirmed_worker_unavailable"
            self.store.update_work_session(
                job_id,
                payload,
                expected_revision=expected_revision,
            )
            return self.get(job_id)

        engine = ZeroCostE2EService(
            store=self.store,
            projects=self.projects,
            paths=self.paths,
            reasoner=self.reasoner,
            planner=self.planner,
            worker=worker,
        )
        pending = PendingReviewResult(
            job_id=job_id,
            project_id=str(snapshot.job["project_id"]),
            reasoning_status=str(execution["reasoning_status"]),
            plan_status=str(execution["plan_status"]),
            worker_status=str(execution["worker_status"]),
            sandbox_root=sandbox_root,
            expected_original_head=expected_head,
            review=review,
        )
        result = engine.finalize_existing_review(
            pending=pending,
            decision=HumanReviewDecision(
                action=action,
                approved_change_fingerprint=fingerprint,
            ),
            verifier_specs=(verifier,),
        )
        payload["apply_status"] = result.apply_status
        payload["recovery_ref"] = result.recovery_ref
        payload["final_result"] = result.as_dict()
        self.store.update_work_session(
            job_id,
            payload,
            expected_revision=expected_revision,
        )
        return self.get(job_id)
