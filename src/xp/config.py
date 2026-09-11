from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from .paths import XPPaths


@dataclass
class XPConfig:
    home: Path
    device_id: str
    control_repo: str | None = None

    @property
    def path(self) -> Path:
        return XPPaths.from_home(self.home).config / "workstation.json"

    @classmethod
    def for_home(cls, home: Path) -> "XPConfig":
        home = Path(home).expanduser().resolve()
        paths = XPPaths.from_home(home)
        paths.ensure_runtime_dirs()
        path = paths.config / "workstation.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(home=home, device_id=str(data["device_id"]), control_repo=data.get("control_repo"))
        cfg = cls(home=home, device_id=uuid.uuid4().hex)
        cfg._save()
        return cfg

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + f".{os.getpid()}.tmp")
        payload = {"config_version": 1, "device_id": self.device_id, "control_repo": self.control_repo}
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)

    def set_control_repo(self, path: Path | None) -> None:
        self.control_repo = str(Path(path).expanduser().resolve()) if path is not None else None
        self._save()
