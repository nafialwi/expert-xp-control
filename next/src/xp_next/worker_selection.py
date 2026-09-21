from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import os
from pathlib import Path
from typing import Mapping

from .lightweight_worker import validate_lightweight_operation_prompt
from .worker_contract import WorkerReadiness


class WorkerSelectionError(ValueError):
    pass


class SelectionStatus(str, Enum):
    SELECTED = "SELECTED"
    RECOMMENDED = "RECOMMENDED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


@dataclass(frozen=True)
class ResourceSnapshot:
    available_memory_mb: int
    logical_cpus: int
    source: str = "injected"

    def __post_init__(self) -> None:
        if self.available_memory_mb < 0:
            raise WorkerSelectionError("available_memory_mb must not be negative")
        if self.logical_cpus < 1:
            raise WorkerSelectionError("logical_cpus must be positive")

    @classmethod
    def probe_local_linux(cls) -> "ResourceSnapshot":
        meminfo = Path("/proc/meminfo")
        if not meminfo.is_file():
            raise WorkerSelectionError("local Linux memory information is unavailable")

        values: dict[str, int] = {}
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            if ":" not in line:
                continue
            key, raw = line.split(":", 1)
            parts = raw.strip().split()
            if not parts:
                continue
            try:
                values[key] = int(parts[0])
            except ValueError:
                continue

        available_kib = values.get("MemAvailable")
        if available_kib is None:
            raise WorkerSelectionError("MemAvailable is missing from /proc/meminfo")

        return cls(
            available_memory_mb=available_kib // 1024,
            logical_cpus=max(1, int(os.cpu_count() or 1)),
            source="local_procfs",
        )

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WorkerResourceProfile:
    backend_id: str
    min_available_memory_mb: int
    min_logical_cpus: int

    def __post_init__(self) -> None:
        if not self.backend_id.strip():
            raise WorkerSelectionError("backend_id must not be empty")
        if self.min_available_memory_mb < 0:
            raise WorkerSelectionError("minimum memory must not be negative")
        if self.min_logical_cpus < 1:
            raise WorkerSelectionError("minimum logical CPU count must be positive")


DEFAULT_RESOURCE_PROFILES: dict[str, WorkerResourceProfile] = {
    "lightweight_local": WorkerResourceProfile(
        backend_id="lightweight_local",
        min_available_memory_mb=32,
        min_logical_cpus=1,
    ),
    "hermes": WorkerResourceProfile(
        backend_id="hermes",
        min_available_memory_mb=4096,
        min_logical_cpus=4,
    ),
}


@dataclass(frozen=True)
class WorkerSelectionRequest:
    worker_prompt: str
    requested_backend: str | None = None

    def __post_init__(self) -> None:
        if not self.worker_prompt.strip():
            raise WorkerSelectionError("worker_prompt must not be empty")
        if len(self.worker_prompt) > 12000:
            raise WorkerSelectionError("worker_prompt exceeds bounded worker size")
        if self.requested_backend is not None and not self.requested_backend.strip():
            raise WorkerSelectionError("requested_backend must not be blank")


@dataclass(frozen=True)
class WorkerSelection:
    status: SelectionStatus
    backend_id: str | None
    detail: str
    explicit: bool
    requires_confirmation: bool
    considered_backends: tuple[str, ...]
    resource_snapshot: ResourceSnapshot

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


def _resource_ok(
    profile: WorkerResourceProfile,
    snapshot: ResourceSnapshot,
) -> tuple[bool, str]:
    if snapshot.available_memory_mb < profile.min_available_memory_mb:
        return (
            False,
            f"{profile.backend_id} requires at least "
            f"{profile.min_available_memory_mb} MiB available memory; "
            f"observed {snapshot.available_memory_mb} MiB",
        )
    if snapshot.logical_cpus < profile.min_logical_cpus:
        return (
            False,
            f"{profile.backend_id} requires at least "
            f"{profile.min_logical_cpus} logical CPUs; "
            f"observed {snapshot.logical_cpus}",
        )
    return True, "PASS"


class WorkerSelector:
    """Decision-only selector. It never executes or silently falls back."""

    def __init__(
        self,
        workers: Mapping[str, object],
        *,
        resource_profiles: Mapping[str, WorkerResourceProfile] | None = None,
    ):
        normalized: dict[str, object] = {}
        for backend_id, worker in workers.items():
            value = str(backend_id).strip()
            if not value:
                raise WorkerSelectionError("worker backend id must not be empty")
            if value in normalized:
                raise WorkerSelectionError(f"duplicate worker backend: {value}")
            normalized[value] = worker
        if not normalized:
            raise WorkerSelectionError("at least one worker is required")
        self.workers = normalized
        self.resource_profiles = dict(
            resource_profiles if resource_profiles is not None else DEFAULT_RESOURCE_PROFILES
        )

    def _readiness(self, backend_id: str) -> WorkerReadiness:
        worker = self.workers[backend_id]
        readiness = worker.readiness()
        if not isinstance(readiness, WorkerReadiness):
            raise WorkerSelectionError(
                f"worker {backend_id} returned an invalid readiness object"
            )
        if readiness.backend_id != backend_id:
            raise WorkerSelectionError(
                f"worker readiness identity mismatch: expected {backend_id}, "
                f"got {readiness.backend_id}"
            )
        return readiness

    def _eligible(
        self,
        backend_id: str,
        *,
        prompt: str,
        resources: ResourceSnapshot,
    ) -> tuple[bool, str]:
        if backend_id not in self.workers:
            return False, f"worker backend is unavailable: {backend_id}"

        if backend_id == "lightweight_local":
            supported, detail = validate_lightweight_operation_prompt(prompt)
            if not supported:
                return False, detail

        readiness = self._readiness(backend_id)
        if not readiness.ready:
            return False, readiness.detail or f"{backend_id} is not ready"

        profile = self.resource_profiles.get(backend_id)
        if profile is not None:
            ok, detail = _resource_ok(profile, resources)
            if not ok:
                return False, detail

        return True, "PASS"

    def select(
        self,
        request: WorkerSelectionRequest,
        *,
        resources: ResourceSnapshot,
    ) -> WorkerSelection:
        considered = tuple(sorted(self.workers))

        if request.requested_backend is not None:
            backend_id = request.requested_backend.strip()
            ok, detail = self._eligible(
                backend_id,
                prompt=request.worker_prompt,
                resources=resources,
            )
            if not ok:
                return WorkerSelection(
                    status=SelectionStatus.NEEDS_ATTENTION,
                    backend_id=None,
                    detail=(
                        f"explicit worker {backend_id} cannot be selected: {detail}. "
                        "No fallback was attempted."
                    ),
                    explicit=True,
                    requires_confirmation=False,
                    considered_backends=(backend_id,),
                    resource_snapshot=resources,
                )
            return WorkerSelection(
                status=SelectionStatus.SELECTED,
                backend_id=backend_id,
                detail=f"explicit worker selected: {backend_id}",
                explicit=True,
                requires_confirmation=False,
                considered_backends=(backend_id,),
                resource_snapshot=resources,
            )

        lightweight_ok, lightweight_detail = self._eligible(
            "lightweight_local",
            prompt=request.worker_prompt,
            resources=resources,
        )
        if lightweight_ok:
            return WorkerSelection(
                status=SelectionStatus.RECOMMENDED,
                backend_id="lightweight_local",
                detail=(
                    "bounded operation fits lightweight_local; explicit confirmation "
                    "is required before execution"
                ),
                explicit=False,
                requires_confirmation=True,
                considered_backends=considered,
                resource_snapshot=resources,
            )

        if "hermes" in self.workers:
            hermes_ok, hermes_detail = self._eligible(
                "hermes",
                prompt=request.worker_prompt,
                resources=resources,
            )
            if hermes_ok:
                return WorkerSelection(
                    status=SelectionStatus.RECOMMENDED,
                    backend_id="hermes",
                    detail=(
                        "task requires the agentic worker and local resources satisfy "
                        "the current Hermes profile; explicit confirmation is required"
                    ),
                    explicit=False,
                    requires_confirmation=True,
                    considered_backends=considered,
                    resource_snapshot=resources,
                )
        else:
            hermes_detail = "Hermes worker is unavailable"

        return WorkerSelection(
            status=SelectionStatus.NEEDS_ATTENTION,
            backend_id=None,
            detail=(
                "no worker can be recommended safely; "
                f"lightweight_local: {lightweight_detail}; hermes: {hermes_detail}"
            ),
            explicit=False,
            requires_confirmation=False,
            considered_backends=considered,
            resource_snapshot=resources,
        )
