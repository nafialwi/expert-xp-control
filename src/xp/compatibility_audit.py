from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LegacyUpgradeStrayArtifact:
    path: Path
    kind: str


def find_legacy_upgrade_stray_artifacts(home: Path) -> tuple[LegacyUpgradeStrayArtifact, ...]:
    """Report inherited rc18.3 upgrade artifacts outside canonical XP root.

    This function is intentionally read-only. It never deletes or repairs
    anything; cleanup requires a separate explicit user-approved action.
    """
    home = Path(home).expanduser().resolve()
    root = home / ".expert-workstation"
    candidates = (
        (home / "active-version", "legacy-active-version"),
        (home / "versions", "legacy-versions-directory"),
    )
    found: list[LegacyUpgradeStrayArtifact] = []
    for path, kind in candidates:
        resolved = path.resolve(strict=False)
        if resolved == root or root in resolved.parents:
            continue
        if path.exists():
            found.append(LegacyUpgradeStrayArtifact(path=path, kind=kind))
    return tuple(found)
