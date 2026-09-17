"""Canonical capability state for XP+ AF-03.

This module is deliberately local/offline by default.
Live probing belongs to the explicit LiveCheckService added in AF-03 Task 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Iterable


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

    def __post_init__(self) -> None:
        if not self.capability_id.strip():
            raise ValueError("capability_id must not be empty")

        if self.checked_at is not None:
            if (
                self.checked_at.tzinfo is None
                or self.checked_at.utcoffset() is None
            ):
                raise ValueError("checked_at must be timezone-aware")


class CapabilityRegistry:
    """Deterministic in-memory capability state.

    Reading local state never performs network or provider calls.
    """

    def __init__(
        self,
        initial: Iterable[CapabilitySnapshot] = (),
    ) -> None:
        self._snapshots: dict[str, CapabilitySnapshot] = {
            snapshot.capability_id: snapshot
            for snapshot in initial
        }

    def get(self, capability_id: str) -> CapabilitySnapshot:
        if capability_id in self._snapshots:
            return self._snapshots[capability_id]

        return CapabilitySnapshot(
            capability_id=capability_id,
            state=CapabilityState.NOT_CHECKED,
            detail="not checked",
            checked_at=None,
            live=False,
        )

    def local_snapshot(self) -> tuple[CapabilitySnapshot, ...]:
        return tuple(
            self._snapshots[key]
            for key in sorted(self._snapshots)
        )

    def record_runtime_failure(
        self,
        capability_id: str,
        detail: str,
        *,
        when: datetime | None = None,
    ) -> CapabilitySnapshot:
        checked_at = when or datetime.now(timezone.utc)

        if (
            checked_at.tzinfo is None
            or checked_at.utcoffset() is None
        ):
            raise ValueError("when must be timezone-aware")

        snapshot = CapabilitySnapshot(
            capability_id=capability_id,
            state=CapabilityState.NEEDS_ATTENTION,
            detail=detail,
            checked_at=checked_at,
            live=False,
        )

        self._snapshots[capability_id] = snapshot
        return snapshot


@dataclass(frozen=True)
class LiveProbe:
    """One explicitly invokable live capability probe."""

    capability_id: str
    run: Callable[[], CapabilitySnapshot]


class LiveCheckService:
    """Explicit-only coordinator for AF-03 live capability checks.

    Construction is passive. Probes run only through run_explicit().
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        probes: tuple[LiveProbe, ...],
        *,
        now: Callable[[], datetime],
    ) -> None:
        self._registry = registry
        self._now = now

        probe_map: dict[str, LiveProbe] = {}
        for probe in probes:
            if probe.capability_id in probe_map:
                raise ValueError(
                    f"duplicate live probe: {probe.capability_id}"
                )
            probe_map[probe.capability_id] = probe

        self._probes = probe_map
        self._probe_order = tuple(
            probe.capability_id
            for probe in probes
        )

    def run_explicit(
        self,
        capability_ids: tuple[str, ...] | None = None,
    ) -> tuple[CapabilitySnapshot, ...]:
        selected = (
            self._probe_order
            if capability_ids is None
            else capability_ids
        )

        results: list[CapabilitySnapshot] = []

        for capability_id in selected:
            probe = self._probes.get(capability_id)

            if probe is None:
                raise ValueError(
                    f"live probe not configured: {capability_id}"
                )

            checked_at = self._now()

            if (
                checked_at.tzinfo is None
                or checked_at.utcoffset() is None
            ):
                raise ValueError(
                    "live check timestamp must be timezone-aware"
                )

            try:
                raw = probe.run()

                if raw.capability_id != capability_id:
                    raise ValueError(
                        "live probe returned mismatched capability_id"
                    )

                snapshot = CapabilitySnapshot(
                    capability_id=raw.capability_id,
                    state=raw.state,
                    detail=raw.detail,
                    checked_at=checked_at,
                    live=True,
                    metadata=dict(raw.metadata),
                )

            except Exception as exc:
                snapshot = CapabilitySnapshot(
                    capability_id=capability_id,
                    state=CapabilityState.NEEDS_ATTENTION,
                    detail=(
                        f"{type(exc).__name__}: "
                        "live probe failed"
                    ),
                    checked_at=checked_at,
                    live=True,
                )

            self._registry._snapshots[
                capability_id
            ] = snapshot

            results.append(snapshot)

        return tuple(results)
