from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class XPPaths:
    home: Path
    root: Path
    runs: Path
    projects: Path
    locks: Path
    logs: Path
    backups: Path
    handoffs: Path
    packages: Path
    versions: Path
    checkpoints: Path
    config: Path

    @classmethod
    def from_home(cls, home: Path) -> "XPPaths":
        home = Path(home).expanduser().resolve()
        root = home / ".expert-workstation"
        return cls(
            home=home,
            root=root,
            runs=root / "runs",
            projects=root / "projects",
            locks=root / "locks",
            logs=root / "logs",
            backups=root / "backups",
            handoffs=root / "handoffs",
            packages=root / "packages",
            versions=root / "versions",
            checkpoints=root / "checkpoints",
            config=root / "config",
        )

    def ensure_runtime_dirs(self) -> None:
        for path in (
            self.root,
            self.runs,
            self.projects,
            self.locks,
            self.logs,
            self.backups,
            self.handoffs,
            self.packages,
            self.versions,
            self.checkpoints,
            self.config,
        ):
            path.mkdir(parents=True, exist_ok=True)
