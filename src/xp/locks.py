import json
import os
from dataclasses import dataclass
from pathlib import Path


class ProjectLockedError(RuntimeError):
    pass


@dataclass
class ProjectLock:
    root: Path
    project_id: str
    run_id: str

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.path = self.root / f"{self.project_id}.lock"
        self._held = False

    def _pid_is_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def inspect(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"status": "UNKNOWN", "path": str(self.path)}
        data["status"] = "ACTIVE" if self._pid_is_alive(int(data.get("pid", -1))) else "STALE"
        return data

    def acquire(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        existing = self.inspect()
        if existing is not None:
            if existing.get("status") == "STALE":
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
            else:
                raise ProjectLockedError(f"Project {self.project_id} already has a lock")
        payload = json.dumps({"pid": os.getpid(), "project_id": self.project_id, "run_id": self.run_id})
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise ProjectLockedError(f"Project {self.project_id} already has a lock") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._held = True

    def release(self) -> None:
        if self._held:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self._held = False
