from __future__ import annotations

from xp.ai.recommendation import (
    RecommendationReport,
    RecommendationState,
)


_COST_LABELS = {
    "free": "Gratis",
    "paid": "Berbayar",
    "unknown": "Biaya belum diketahui",
}

_STATE_LABELS = {
    RecommendationState.CONSIDER: "Dapat dipertimbangkan",
    RecommendationState.REQUIRES_APPROVAL: "Perlu persetujuan",
    RecommendationState.BLOCKED: "Diblokir",
    RecommendationState.NEEDS_ATTENTION: "Perlu perhatian",
    RecommendationState.NOT_CHECKED: "Belum diperiksa",
    RecommendationState.NOT_SUITABLE: "Tidak sesuai",
}


def format_cost_label(cost_class: str) -> str:
    try:
        return _COST_LABELS[str(cost_class)]
    except KeyError as exc:
        raise ValueError(
            f"Unknown cost class: {cost_class!r}"
        ) from exc


def _token(value: int | None) -> str:
    return "Tidak tersedia" if value is None else str(value)


def _served_model(record) -> str:
    value = getattr(record, "served_model", None)
    return value if value else "Tidak tersedia"


def format_usage_compact(record) -> str:
    return (
        f"{record.route_id} | "
        f"{record.configured_model} | "
        f"{format_cost_label(record.cost_class)} | "
        f"Token: {_token(record.total_tokens)} | "
        f"Hasil: {record.technical_result}"
    )


def format_usage_expanded(record) -> str:
    error_type = getattr(record, "error_type", None)
    return "\n".join(
        (
            f"Job: {record.job_id or 'Tidak tersedia'}",
            f"Route: {record.route_id}",
            f"Transport: {record.transport}",
            f"Model dikonfigurasi: {record.configured_model}",
            f"Model dilayani: {_served_model(record)}",
            f"Biaya: {format_cost_label(record.cost_class)}",
            f"Latency: {record.latency_ms} ms",
            f"Token input: {_token(record.input_tokens)}",
            f"Token output: {_token(record.output_tokens)}",
            f"Token total: {_token(record.total_tokens)}",
            f"Hasil teknis: {record.technical_result}",
            f"Error: {error_type or 'Tidak tersedia'}",
            f"Waktu: {record.timestamp.isoformat()}",
        )
    )


def _item_compact(item) -> str:
    state = _STATE_LABELS[item.state]
    line = (
        f"{item.route_id} / {item.model} — {state} — "
        f"{item.comparable_jobs} pekerjaan sejenis"
    )
    if item.limitations:
        line += f" — {item.limitations[0]}"
    return line


def format_recommendation_compact(
    rec: RecommendationReport,
) -> str:
    lines = [rec.headline]
    lines.extend(_item_compact(item) for item in rec.items)
    lines.append("Pilihan tetap di tangan pengguna.")
    return "\n".join(lines)


def format_recommendation_expanded(
    rec: RecommendationReport,
) -> str:
    lines = [
        rec.headline,
        f"Kategori: {rec.task_category.value}",
    ]

    for item in rec.items:
        lines.append("")
        lines.append(
            f"{item.route_id} / {item.model} — "
            f"{_STATE_LABELS[item.state]}"
        )
        lines.append(
            f"Riwayat sejenis: {item.comparable_jobs} job"
        )
        lines.append(
            f"Job dengan feedback: {item.feedback_jobs}"
        )

        lines.append("Bukti:")
        if item.evidence_notes:
            lines.extend(f"- {note}" for note in item.evidence_notes)
        else:
            lines.append("- Belum ada bukti tambahan.")

        if item.feedback_summary is not None:
            summary = item.feedback_summary
            lines.append(
                "Feedback pengguna: "
                f"Bagus {summary.good}, "
                f"Cukup {summary.adequate}, "
                f"Kurang sesuai {summary.poor}."
            )

        lines.append("Keterbatasan:")
        if item.limitations:
            lines.extend(
                f"- {limitation}"
                for limitation in item.limitations
            )
        else:
            lines.append(
                "- Tidak ada keterbatasan tambahan yang tercatat."
            )

    lines.append("")
    lines.append("Pilihan tetap di tangan pengguna.")
    return "\n".join(lines)
