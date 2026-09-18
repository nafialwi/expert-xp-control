from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Mapping

from .contracts import AIRoute


COST_CLASSES = frozenset({"free", "paid", "unknown"})
COST_EVIDENCE_MAX_AGE = timedelta(days=30)


class CostEvidenceError(RuntimeError):
    """Raised when AF-04 cost evidence is invalid."""


class CostScope(str, Enum):
    LOCAL = "local"
    ONLINE = "online"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CostEvidence:
    route_id: str
    observed_cost_class: str
    verified_at: datetime
    source: str
    scope: CostScope

    def __post_init__(self) -> None:
        if not self.route_id:
            raise ValueError("route_id must be non-empty")
        if self.observed_cost_class not in COST_CLASSES:
            raise ValueError("invalid observed cost class")
        if self.verified_at.tzinfo is None:
            raise ValueError("verified_at must be timezone-aware")
        if not self.source:
            raise ValueError("source must be non-empty")


def is_stale(
    evidence: CostEvidence,
    *,
    now: datetime,
) -> bool:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if evidence.scope is not CostScope.ONLINE:
        return False
    return now - evidence.verified_at > COST_EVIDENCE_MAX_AGE


def effective_cost_class(
    route: AIRoute,
    evidence: CostEvidence | None,
) -> str:
    if evidence is None:
        return route.cost_class
    if evidence.route_id != route.route_id:
        raise CostEvidenceError(
            "Cost evidence route_id does not match selected route"
        )
    return evidence.observed_cost_class


class CostEvidenceStore:
    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()

    @classmethod
    def for_home(cls, home: Path) -> "CostEvidenceStore":
        base = Path(home).expanduser().resolve()
        root = (
            base
            / ".expert-workstation"
            / "state"
            / "ai"
            / "cost-evidence"
        )
        return cls(root)

    def _path_for(self, route_id: str) -> Path:
        if not isinstance(route_id, str) or not route_id:
            raise ValueError("route_id must be a non-empty string")
        digest = hashlib.sha256(
            route_id.encode("utf-8")
        ).hexdigest()
        return self.root / f"{digest}.json"

    def put(self, evidence: CostEvidence) -> None:
        path = self._path_for(evidence.route_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "route_id": evidence.route_id,
            "observed_cost_class": evidence.observed_cost_class,
            "verified_at": evidence.verified_at.isoformat(),
            "source": evidence.source,
            "scope": evidence.scope.value,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"

        temp = path.with_name(
            f".{path.name}.tmp-{os.getpid()}"
        )
        try:
            temp.write_text(encoded, encoding="utf-8")
            temp.replace(path)
        except OSError as exc:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            raise CostEvidenceError(
                "Unable to persist cost evidence"
            ) from exc

    def get(self, route_id: str) -> CostEvidence | None:
        path = self._path_for(route_id)
        if not path.exists():
            return None

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CostEvidenceError(
                "Unable to read cost evidence"
            ) from exc

        if not isinstance(raw, Mapping):
            raise CostEvidenceError(
                "Persisted cost evidence must be an object"
            )

        if raw.get("route_id") != route_id:
            raise CostEvidenceError(
                "Persisted cost evidence route_id mismatch"
            )

        try:
            verified_at = datetime.fromisoformat(
                str(raw["verified_at"])
            )
            scope = CostScope(str(raw["scope"]))
            observed_cost_class = str(
                raw["observed_cost_class"]
            )
            source = str(raw["source"])
        except (
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise CostEvidenceError(
                "Persisted cost evidence is invalid"
            ) from exc

        try:
            return CostEvidence(
                route_id=route_id,
                observed_cost_class=observed_cost_class,
                verified_at=verified_at,
                source=source,
                scope=scope,
            )
        except ValueError as exc:
            raise CostEvidenceError(
                "Persisted cost evidence is invalid"
            ) from exc
