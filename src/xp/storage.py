from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StorageReport:
    ok: bool
    free_bytes: int
    required_bytes: int
    path: Path


class StorageManager:
    def __init__(self, path: Path):
        self.path = Path(path)

    def preflight(self, required_bytes: int) -> StorageReport:
        usage = shutil.disk_usage(self.path)
        return StorageReport(
            ok=usage.free >= required_bytes,
            free_bytes=usage.free,
            required_bytes=required_bytes,
            path=self.path,
        )

    def cleanup_oldest(self, directory: Path, keep: int = 3, pattern: str = "*") -> list[Path]:
        directory = Path(directory)
        if not directory.exists():
            return []
        candidates = [p for p in directory.glob(pattern) if p.is_file()]
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        removed: list[Path] = []
        for path in candidates[keep:]:
            path.unlink(missing_ok=True)
            removed.append(path)
        return removed
