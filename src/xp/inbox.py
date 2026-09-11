from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .packages import PackageError, PackageManifest, RunContext, inspect_package, validate_package


@dataclass(frozen=True)
class PackageCandidate:
    path: Path
    manifest: PackageManifest
    exact_match: bool
    compatibility_reason: str
    modified_at: float
    score: int


def _score(manifest: PackageManifest, context: RunContext) -> tuple[int, bool, str]:
    report = validate_package(manifest, context)
    if report.status == "CLEAR":
        if (
            manifest.package_type == "REMEDIATION"
            and manifest.run_id == context.run_id
            and manifest.incident_id == context.incident_id
            and manifest.incident_challenge == context.incident_challenge
        ):
            return 100, True, "exact remediation match"
        return 80, True, "compatible package"
    score = 0
    if manifest.project_id == context.project_id:
        score += 20
    if manifest.base_fingerprint == context.base_fingerprint:
        score += 10
    if manifest.expected_state == context.stage:
        score += 10
    if manifest.run_id and manifest.run_id == context.run_id:
        score += 10
    if manifest.incident_id and manifest.incident_id == context.incident_id:
        score += 10
    return score, False, "; ".join(report.reasons)


def scan_inbox(paths: list[Path], context: RunContext, limit: int = 4) -> list[PackageCandidate]:
    candidates: list[PackageCandidate] = []
    seen: set[Path] = set()
    for root in paths:
        root = Path(root).expanduser()
        if not root.exists():
            continue
        for path in root.glob("*.zip"):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                manifest = inspect_package(path)
            except (PackageError, OSError):
                continue
            score, exact, reason = _score(manifest, context)
            candidates.append(
                PackageCandidate(
                    path=path,
                    manifest=manifest,
                    exact_match=exact,
                    compatibility_reason=reason,
                    modified_at=path.stat().st_mtime,
                    score=score,
                )
            )
    candidates.sort(key=lambda c: (c.score, c.modified_at), reverse=True)
    return candidates[:limit]
