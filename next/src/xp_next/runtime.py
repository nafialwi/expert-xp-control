from __future__ import annotations

from pathlib import Path

from .runtime_paths import RuntimePaths
from .state_store import StateStore


class XPRuntime:
    def __init__(self, paths: RuntimePaths, store: StateStore):
        self.paths = paths
        self.store = store

    @classmethod
    def open(cls, home: Path | str | None = None) -> "XPRuntime":
        paths = RuntimePaths.resolve(home).ensure()
        return cls(paths=paths, store=StateStore(paths.database))

    def __enter__(self) -> "XPRuntime":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self.store.close()
