from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable
from uuid import uuid4

from xp.activity import (
    ActivityCategory,
    ActivityEvent,
    ActivityStatus,
    ActivityStore,
    Provenance,
)
from xp.ai.agents.base import AgentRunRequest, AgentRunResult, AgentRuntime


class GovernanceError(RuntimeError):
    pass


class ApprovalRequiredError(GovernanceError):
    pass


class WorkspaceBoundaryError(GovernanceError):
    pass


class WorkerNotReadyError(GovernanceError):
    pass


class UnauthorizedMutationError(GovernanceError):
    pass


class ProtectedRepoMutationError(GovernanceError):
    pass


class SnapshotLimitError(GovernanceError):
    pass


class ApprovalClass(str, Enum):
    READ_ONLY = "READ_ONLY"
    WRITE_ALLOWED = "WRITE_ALLOWED"
    HIGH_RISK_CONFIRM = "HIGH_RISK_CONFIRM"


class ExecutionRisk(str, Enum):
    READ_ONLY = "read_only"
    WRITE = "write"
    HIGH_RISK = "high_risk"


@dataclass(frozen=True)
class ExecutionScope:
    root: Path
    cwd: Path

    def __post_init__(self) -> None:
        root = self.root.expanduser().resolve()
        cwd = self.cwd.expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise WorkspaceBoundaryError("scope root must be an existing directory")
        if not cwd.exists() or not cwd.is_dir():
            raise WorkspaceBoundaryError("cwd must be an existing directory")
        try:
            cwd.relative_to(root)
        except ValueError as exc:
            raise WorkspaceBoundaryError(
                "cwd must be inside approved workspace root"
            ) from exc
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "cwd", cwd)


@dataclass(frozen=True)
class ApprovalGrant:
    job_id: str
    approval_class: ApprovalClass
    approved: bool
    scope_root: Path

    def __post_init__(self) -> None:
        if not self.job_id.strip():
            raise ValueError("job_id must not be empty")
        object.__setattr__(self, "scope_root", self.scope_root.expanduser().resolve())


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    summary: str

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("verification summary must not be empty")


@dataclass(frozen=True)
class MutationRecord:
    path: str
    before_sha256: str | None
    after_sha256: str | None


@dataclass(frozen=True)
class GovernedExecutionResult:
    status: str
    worker_result: AgentRunResult | None
    attempts: int
    mutations: tuple[MutationRecord, ...]
    verification: VerificationResult
    recovery_id: str
    rollback_performed: bool


Verifier = Callable[[Path, AgentRunResult], VerificationResult]
RecoveryFactory = Callable[[Path], str]
Rollback = Callable[[str], None]


def _approval_allows(approval_class: ApprovalClass, risk: ExecutionRisk) -> bool:
    if risk is ExecutionRisk.READ_ONLY:
        return approval_class in {
            ApprovalClass.READ_ONLY,
            ApprovalClass.WRITE_ALLOWED,
            ApprovalClass.HIGH_RISK_CONFIRM,
        }
    if risk is ExecutionRisk.WRITE:
        return approval_class in {
            ApprovalClass.WRITE_ALLOWED,
            ApprovalClass.HIGH_RISK_CONFIRM,
        }
    return approval_class is ApprovalClass.HIGH_RISK_CONFIRM


def _validate_approval(*, grant, scope, risk, job_id) -> None:
    if not grant.approved:
        raise ApprovalRequiredError("worker execution is not approved")
    if grant.job_id != job_id:
        raise ApprovalRequiredError("approval job_id does not match execution")
    if grant.scope_root != scope.root:
        raise ApprovalRequiredError("approval workspace does not match execution")
    if not _approval_allows(grant.approval_class, risk):
        raise ApprovalRequiredError(
            f"{grant.approval_class.value} does not authorize {risk.value}"
        )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_workspace(root: Path, *, max_files=5000, max_total_bytes=64 * 1024 * 1024):
    root = root.resolve()
    result: dict[str, str] = {}
    count = 0
    total = 0
    for path in sorted(root.rglob("*")):
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if ".git" in rel.parts or "__pycache__" in rel.parts:
            continue
        if path.is_symlink():
            result[rel.as_posix()] = "SYMLINK:" + str(path.readlink())
            continue
        if not path.is_file():
            continue
        count += 1
        total += path.stat().st_size
        if count > max_files or total > max_total_bytes:
            raise SnapshotLimitError("workspace snapshot safety limit exceeded")
        result[rel.as_posix()] = _sha(path)
    return result


def diff_snapshots(before, after) -> tuple[MutationRecord, ...]:
    rows = []
    for path in sorted(set(before) | set(after)):
        old = before.get(path)
        new = after.get(path)
        if old != new:
            rows.append(MutationRecord(path, old, new))
    return tuple(rows)


def git_state(repo: Path | None):
    if repo is None:
        return None
    repo = repo.expanduser().resolve()
    probe = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if probe.returncode != 0:
        raise ProtectedRepoMutationError("protected_repo is not a git worktree")
    h = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True,
    ).stdout.strip()
    s = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True,
    ).stdout
    return h, s


class GovernedWorker:
    def __init__(self, runtime: AgentRuntime, *, activity_store=None, protected_repo=None, max_remediation=1):
        if max_remediation < 0 or max_remediation > 3:
            raise ValueError("max_remediation must be between 0 and 3")
        self.runtime = runtime
        self.activity_store = activity_store
        self.protected_repo = protected_repo
        self.max_remediation = max_remediation

    def _record(self, *, job_id, action, status, summary, metadata=None):
        if self.activity_store is None:
            return
        self.activity_store.append(
            ActivityEvent(
                event_id=str(uuid4()),
                job_id=job_id,
                timestamp=datetime.now(timezone.utc),
                category=ActivityCategory.AGENT,
                action=action,
                provenance=Provenance(
                    source="local_project",
                    processor=self.runtime.name(),
                    via="governed_worker",
                    live=False,
                ),
                status=status,
                result_summary=summary,
                metadata=dict(metadata or {}),
            )
        )

    def execute(self, *, job_id, request, scope, risk, approval, verifier, create_recovery, rollback):
        _validate_approval(grant=approval, scope=scope, risk=risk, job_id=job_id)
        self._record(
            job_id=job_id,
            action="Worker approval",
            status=ActivityStatus.COMPLETED,
            summary="Explicit worker approval validated",
            metadata={"approval_class": approval.approval_class.value, "risk": risk.value},
        )

        if request.cwd is None:
            raise WorkspaceBoundaryError("worker request cwd is required")
        if request.cwd.expanduser().resolve() != scope.cwd:
            raise WorkspaceBoundaryError("request cwd must equal approved execution cwd")

        readiness = self.runtime.readiness()
        if not readiness.ready:
            self._record(
                job_id=job_id,
                action="Worker readiness",
                status=ActivityStatus.NEEDS_ATTENTION,
                summary="Worker runtime is not ready",
                metadata={"worker_status": readiness.status},
            )
            raise WorkerNotReadyError("worker runtime is not ready")
        self._record(
            job_id=job_id,
            action="Worker readiness",
            status=ActivityStatus.COMPLETED,
            summary="Worker runtime is ready",
            metadata={"worker_status": readiness.status},
        )

        recovery_id = create_recovery(scope.root)
        if not isinstance(recovery_id, str) or not recovery_id.strip():
            raise GovernanceError("recovery factory must return a recovery id")
        self._record(
            job_id=job_id,
            action="Recovery point",
            status=ActivityStatus.COMPLETED,
            summary="Recovery point created before worker execution",
            metadata={"recovery": "created"},
        )

        protected_before = git_state(self.protected_repo)
        before = snapshot_workspace(scope.root)
        mutations_seen: dict[str, MutationRecord] = {}
        attempts = 0
        current_request = request
        last_result = None
        last_verification = VerificationResult(False, "Worker has not run")

        while attempts <= self.max_remediation:
            attempts += 1
            self._record(
                job_id=job_id,
                action="Worker execution",
                status=ActivityStatus.STARTED,
                summary=f"Worker attempt {attempts} started",
                metadata={"attempt": attempts},
            )
            try:
                last_result = self.runtime.run(current_request)
            except Exception as exc:
                last_result = AgentRunResult(status="FAILED", output="", returncode=1)
                self._record(
                    job_id=job_id,
                    action="Worker execution",
                    status=ActivityStatus.FAILED,
                    summary=f"{type(exc).__name__}: worker execution failed",
                    metadata={"attempt": attempts},
                )
            else:
                self._record(
                    job_id=job_id,
                    action="Worker execution",
                    status=(ActivityStatus.COMPLETED if last_result.returncode in (None, 0) else ActivityStatus.FAILED),
                    summary=f"Worker attempt {attempts} finished",
                    metadata={
                        "attempt": attempts,
                        "returncode": last_result.returncode,
                        "worker_status": last_result.status,
                    },
                )

            if git_state(self.protected_repo) != protected_before:
                rollback(recovery_id)
                self._record(
                    job_id=job_id,
                    action="Protected repository integrity",
                    status=ActivityStatus.NEEDS_ATTENTION,
                    summary="Protected repository changed during worker execution",
                )
                raise ProtectedRepoMutationError("protected repository changed during worker execution")

            after = snapshot_workspace(scope.root)
            mutations = diff_snapshots(before, after)
            for item in mutations:
                mutations_seen[item.path] = item
            self._record(
                job_id=job_id,
                action="Mutation audit",
                status=ActivityStatus.COMPLETED,
                summary=f"Mutation audit recorded {len(mutations)} changed path(s)",
                metadata={"mutation_count": len(mutations), "paths": [m.path for m in mutations]},
            )

            if risk is ExecutionRisk.READ_ONLY and mutations:
                rollback(recovery_id)
                self._record(
                    job_id=job_id,
                    action="READ_ONLY enforcement",
                    status=ActivityStatus.NEEDS_ATTENTION,
                    summary="Unauthorized mutation detected and rolled back",
                    metadata={"mutation_count": len(mutations)},
                )
                raise UnauthorizedMutationError("READ_ONLY worker mutated approved workspace")

            last_verification = verifier(scope.root, last_result)
            self._record(
                job_id=job_id,
                action="Verifier",
                status=(ActivityStatus.COMPLETED if last_verification.passed else ActivityStatus.FAILED),
                summary=last_verification.summary,
                metadata={"attempt": attempts},
            )

            if last_result.returncode in (None, 0) and last_verification.passed:
                return GovernedExecutionResult(
                    status="COMPLETED",
                    worker_result=last_result,
                    attempts=attempts,
                    mutations=tuple(mutations_seen.values()),
                    verification=last_verification,
                    recovery_id=recovery_id,
                    rollback_performed=False,
                )

            if attempts <= self.max_remediation:
                self._record(
                    job_id=job_id,
                    action="Bounded remediation",
                    status=ActivityStatus.STARTED,
                    summary="Bounded remediation attempt authorized",
                    metadata={"next_attempt": attempts + 1},
                )
                current_request = AgentRunRequest(
                    prompt=(
                        request.prompt
                        + "\n\nVerifier feedback: "
                        + last_verification.summary
                        + "\nRepair only the approved workspace and satisfy the verifier."
                    ),
                    cwd=scope.cwd,
                )
                continue

            rollback(recovery_id)
            self._record(
                job_id=job_id,
                action="Bounded remediation",
                status=ActivityStatus.NEEDS_ATTENTION,
                summary="Remediation budget exhausted; recovery restored",
                metadata={"attempts": attempts},
            )
            return GovernedExecutionResult(
                status="NEEDS_ATTENTION",
                worker_result=last_result,
                attempts=attempts,
                mutations=tuple(mutations_seen.values()),
                verification=last_verification,
                recovery_id=recovery_id,
                rollback_performed=True,
            )

        raise AssertionError("unreachable")
