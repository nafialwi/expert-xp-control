import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .models import RunState
from .paths import XPPaths


class StateNotFoundError(FileNotFoundError):
    pass


class StateStore:
    def __init__(self, paths: XPPaths):
        self.paths = paths

    def _run_dir(self, run_id: str) -> Path:
        return self.paths.runs / run_id

    def save(self, state: RunState) -> None:
        self.paths.ensure_runtime_dirs()
        run_dir = self._run_dir(state.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        final_path = run_dir / "state.json"
        tmp_path = run_dir / f"state.{os.getpid()}.tmp"
        updated = replace(state, updated_at=datetime.now(timezone.utc).isoformat())
        payload = json.dumps(updated.to_dict(), indent=2, sort_keys=True) + "\n"
        with tmp_path.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, final_path)
        try:
            dir_fd = os.open(run_dir, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass

    def load(self, run_id: str) -> RunState:
        path = self._run_dir(run_id) / "state.json"
        if not path.exists():
            raise StateNotFoundError(run_id)
        return RunState.from_dict(json.loads(path.read_text(encoding="utf-8")))
