from __future__ import annotations

from dataclasses import asdict, dataclass

from .worker_selection import (
    ConfirmationStatus,
    WorkerConfirmation,
    WorkerSelection,
)


@dataclass(frozen=True)
class WorkerChoiceView:
    title: str
    status: str
    backend_id: str | None
    detail: str
    resource_memory_mb: int
    logical_cpus: int
    confirmation_required: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def build_worker_choice_view(selection: WorkerSelection) -> WorkerChoiceView:
    backend = selection.backend_id
    if selection.status.value == "NEEDS_ATTENTION":
        title = "Worker belum dapat dipilih"
    elif selection.explicit:
        title = "Worker yang dipilih"
    else:
        title = "Worker yang disarankan"
    return WorkerChoiceView(
        title=title,
        status=selection.status.value,
        backend_id=backend,
        detail=selection.detail,
        resource_memory_mb=selection.resource_snapshot.available_memory_mb,
        logical_cpus=selection.resource_snapshot.logical_cpus,
        confirmation_required=(
            selection.requires_confirmation or selection.backend_id is not None
        ),
    )


def render_worker_choice(selection: WorkerSelection) -> str:
    view = build_worker_choice_view(selection)
    backend = view.backend_id or "-"
    lines = [
        "XP Next — Pemilihan Worker",
        "",
        f"{view.title}: {backend}",
        f"Status: {view.status}",
        f"Alasan: {view.detail}",
        (
            "Resource: "
            f"{view.resource_memory_mb} MiB tersedia / "
            f"{view.logical_cpus} logical CPU"
        ),
    ]
    if view.backend_id is not None:
        lines.extend(
            [
                "Konfirmasi: diperlukan sebelum worker dijalankan",
                "",
                f"[1] Gunakan {view.backend_id}",
                "[0] Batal",
            ]
        )
    return "\n".join(lines)


def render_worker_confirmation(confirmation: WorkerConfirmation) -> str:
    if confirmation.status is ConfirmationStatus.CONFIRMED:
        headline = f"Worker dikonfirmasi: {confirmation.backend_id}"
    elif confirmation.status is ConfirmationStatus.DECLINED:
        headline = "Pemilihan worker dibatalkan"
    else:
        headline = "Worker perlu perhatian"
    return "\n".join(
        [
            headline,
            f"Status: {confirmation.status.value}",
            f"Detail: {confirmation.detail}",
        ]
    )
