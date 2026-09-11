from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class WarningClassification:
    status: str
    known: tuple[str, ...]
    unknown: tuple[str, ...]


def classify_warnings(text: str, *, known_markers: list[str] | tuple[str, ...], detect_markers: list[str] | tuple[str, ...]) -> WarningClassification:
    present = [m for m in detect_markers if m and m in text]
    if not present:
        return WarningClassification('CLEAR', (), ())
    known_set = set(known_markers)
    known = tuple(m for m in present if m in known_set)
    unknown = tuple(m for m in present if m not in known_set)
    return WarningClassification('WARNING' if unknown else 'KNOWN', known, unknown)
