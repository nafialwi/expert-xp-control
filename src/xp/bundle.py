from __future__ import annotations

import dataclasses
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from . import __version__
from .config import XPConfig
from .project_doctor import ProjectDoctor
from .project_registry import ProjectRegistry, load_project_profile
from .redaction import sanitize_mapping
from .schema import schema_catalog


@dataclass(frozen=True)
class BundleArtifact:
    path: Path
    mode: str
    size_bytes: int


class BundleBuilder:
    """Build compact or deep AI context bundles without mutating project source."""

    COMPACT_TEXT_LIMIT = 6000

    def __init__(
        self,
        home: Path,
        *,
        engine_root: Path | None = None,
    ):
        self.home = Path(home).expanduser().resolve()
        self.engine_root = (
            Path(engine_root).expanduser().resolve()
            if engine_root is not None
            else Path(__file__).resolve().parent
        )

    @staticmethod
    def _read_optional(path: Path) -> str:
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    @classmethod
    def _bounded(cls, text: str) -> str:
        if len(text) <= cls.COMPACT_TEXT_LIMIT:
            return text
        omitted = len(text) - cls.COMPACT_TEXT_LIMIT
        return (
            text[: cls.COMPACT_TEXT_LIMIT]
            + f"\n\n[COMPACT BUNDLE: {omitted} chars omitted; use --deep for full snapshot]\n"
        )

    @staticmethod
    def _safe_run_dict(run) -> dict:
        raw = dataclasses.asdict(run)
        sanitized = sanitize_mapping(raw)
        return sanitized if isinstance(sanitized, dict) else raw

    def _registry_lines(self) -> list[str]:
        registry = ProjectRegistry.for_home(self.home)
        lines = []
        for item in registry.list_projects():
            lines.append(
                f"- {item.project_id} | {item.name} | "
                f"repo: {item.repo_path or '(remote-only)'}"
            )
        return lines or ["- (registry empty)"]

    @staticmethod
    def _locked_milestones(checkpoints_root: Path, project_id: str) -> list[str]:
        root = checkpoints_root / project_id
        if not root.is_dir():
            return []
        result: list[str] = []
        for child in sorted(root.iterdir()):
            if child.is_dir():
                result.append(child.name)
            elif child.is_file() and child.suffix.lower() == ".json":
                result.append(child.stem)
        return result

    @staticmethod
    def _latest_run(runs_root: Path, project_id: str):
        if not runs_root.is_dir():
            return None
        candidates: list[tuple[float, object]] = []
        from .models import RunState
        for state_file in runs_root.glob("*/STATE.json"):
            try:
                state = RunState.load(state_file)
            except Exception:
                continue
            if state.project_id == project_id:
                candidates.append((state_file.stat().st_mtime, state))
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]

    def _engine_source(self) -> Iterable[str]:
        for py in sorted(self.engine_root.rglob("*.py")):
            try:
                label = py.relative_to(self.engine_root).as_posix()
            except ValueError:
                label = py.name
            yield f"##### FILE: {label} #####"
            yield py.read_text(encoding="utf-8", errors="replace")

    def compact(self, repo: Path) -> str:
        """Return the locked-plan compact bundle string using the stable builder."""
        artifact = self.build(repo, deep=False)
        return artifact.path.read_text(encoding="utf-8")

    def deep(self, repo: Path) -> str:
        """Return the locked-plan deep bundle string using the stable builder."""
        artifact = self.build(repo, deep=True)
        return artifact.path.read_text(encoding="utf-8")

    def build(
        self,
        repo: Path,
        *,
        deep: bool = False,
        output_dir: Path | None = None,
    ) -> BundleArtifact:
        repo = Path(repo).expanduser().resolve()
        if not (repo / ".xp" / "project.json").is_file():
            raise ValueError(
                f"{repo} is not an XP project: .xp/project.json is missing"
            )

        profile = load_project_profile(repo)
        root = self.home / ".expert-workstation"
        cfg = XPConfig.for_home(self.home)
        mode = "DEEP" if deep else "COMPACT"
        lines: list[str] = []

        lines.append("# XP CONTEXT BUNDLE — BACA DULU SEBELUM MENJAWAB")
        lines.append(f"XP version: {__version__}")
        lines.append(f"Generated: {time.strftime('%Y-%m-%dT%H:%M:%S')}")
        lines.append(f"Bundle mode: {mode}")
        lines.append(f"Device ID: {cfg.device_id}")
        lines.append("")
        lines.append("INSTRUKSI UNTUK AI PENERIMA:")
        lines.append("Gunakan bundle ini sebagai konteks project dan kontrak XP.")
        lines.append("Jangan melakukan mutasi project di luar workflow XP.")
        lines.append("Gunakan schema kanonik dari bagian XP SCHEMA saat membuat spec.")
        if not deep:
            lines.append(
                "Bundle ini COMPACT. Minta `xp bundle --repo <repo> --deep` "
                "hanya bila source engine penuh benar-benar diperlukan."
            )
        lines.append("")

        lines.append("===== PROJECT IDENTITY =====")
        lines.append(f"Project ID: {profile.project_id}")
        lines.append(f"Project name: {profile.name}")
        lines.append(f"Repo: {repo}")
        lines.append("")

        lines.append("===== PROJECT REGISTRY =====")
        lines.extend(self._registry_lines())
        lines.append("")

        for title, rel in (
            ("PROFILE (.xp/project.json)", ".xp/project.json"),
            ("POLICIES (.xp/policies.json)", ".xp/policies.json"),
            ("COMPATIBILITY (.xp/compatibility.json)", ".xp/compatibility.json"),
        ):
            lines.append(f"===== {title} =====")
            lines.append(self._read_optional(repo / rel) or "{}")

        lines.append("===== PROJECT DOCTOR =====")
        doctor = ProjectDoctor(self.home).inspect(repo)
        lines.append(json.dumps(doctor.to_dict(), indent=2, sort_keys=True))

        lines.append("===== XP SCHEMA =====")
        lines.append(json.dumps(schema_catalog(), indent=2, sort_keys=True))

        blueprint = repo / "docs" / "blueprint" / "15_WORKFLOW_PROFILE.md"
        if blueprint.is_file():
            lines.append("===== BLUEPRINT SNAPSHOT (15_WORKFLOW_PROFILE.md) =====")
            text = self._read_optional(blueprint)
            lines.append(text if deep else self._bounded(text))

        roadmap = repo / "docs" / "checkpoints" / "ROADMAP_PROGRESS.md"
        if roadmap.is_file():
            lines.append("===== ROADMAP SNAPSHOT (ROADMAP_PROGRESS.md) =====")
            text = self._read_optional(roadmap)
            lines.append(text if deep else self._bounded(text))

        lines.append("===== CHECKPOINTS TERKUNCI (via XP) =====")
        locked = self._locked_milestones(root / "checkpoints", profile.project_id)
        lines.extend(f"- {milestone}" for milestone in locked)
        if not locked:
            lines.append("- (none detected)")

        latest = self._latest_run(root / "runs", profile.project_id)
        if latest is not None:
            lines.append("===== RUN STATE TERAKHIR =====")
            lines.append(
                json.dumps(
                    self._safe_run_dict(latest),
                    indent=2,
                    default=str,
                    sort_keys=True,
                )
            )

        lines.append("===== SOURCE ENGINE XP =====")
        if deep:
            lines.extend(self._engine_source())
        else:
            lines.append(
                "[OMITTED IN COMPACT MODE — use `xp bundle --repo <repo> --deep` "
                "for full engine source.]"
            )

        out_dir = (
            Path(output_dir).expanduser().resolve()
            if output_dir is not None
            else self.home / "storage" / "downloads" / "Expert"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        suffix = "_DEEP" if deep else ""
        out = out_dir / f"XP_BUNDLE_{profile.project_id}_{stamp}{suffix}.txt"
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")

        return BundleArtifact(
            path=out,
            mode=mode,
            size_bytes=out.stat().st_size,
        )
