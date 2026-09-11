from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .redaction import sanitize_mapping


@dataclass
class CheckpointContext:
    project_id: str
    project_name: str
    milestone: str
    stage: str
    source_paths: list[Path] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    run_id: str | None = None
    commit: str | None = None


@dataclass(frozen=True)
class CheckpointArtifacts:
    report: Path
    sha256s: Path
    state: Path
    source_archive: Path | None = None


class CheckpointBuilder:
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)

    @staticmethod
    def _sha(path: Path) -> str:
        h = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def _create_source_archive(self, repo: Path) -> Path:
        archive = self.output_dir / "SOURCE.zip"
        result = subprocess.run(
            ["git", "archive", "--format=zip", "--output", str(archive), "HEAD"],
            cwd=repo,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "git archive failed")
        return archive

    def build(self, context: CheckpointContext, *, repo: Path | None = None) -> CheckpointArtifacts:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        safe_evidence = sanitize_mapping(context.evidence)
        timestamp = datetime.now(timezone.utc).isoformat()
        report = self.output_dir / "CHECKPOINT.md"
        state = self.output_dir / "CHECKPOINT_STATE.json"
        sha_file = self.output_dir / "SHA256SUMS.txt"
        source_archive = self._create_source_archive(Path(repo).resolve()) if repo is not None else None
        source_hashes = {
            str(Path(path)): self._sha(Path(path))
            for path in context.source_paths
            if Path(path).is_file()
        }
        report.write_text(
            "\n".join(
                [
                    f"# {context.project_name} — {context.milestone} Checkpoint",
                    "",
                    f"Project ID: `{context.project_id}`",
                    f"Run: `{context.run_id or '-'}`",
                    f"Stage: `{context.stage}`",
                    f"Commit: `{context.commit or '-'}`",
                    f"Created: `{timestamp}`",
                    "",
                    "## Evidence",
                    "",
                    "```json",
                    json.dumps(safe_evidence, indent=2, sort_keys=True),
                    "```",
                    "",
                    "## Source hashes",
                    "",
                    *[f"- `{digest}`  `{path}`" for path, digest in source_hashes.items()],
                    "",
                ]
            ),
            encoding="utf-8",
        )
        state.write_text(
            json.dumps(
                {
                    "project_id": context.project_id,
                    "project_name": context.project_name,
                    "milestone": context.milestone,
                    "stage": context.stage,
                    "run_id": context.run_id,
                    "commit": context.commit,
                    "created_at": timestamp,
                    "evidence": safe_evidence,
                    "source_hashes": source_hashes,
                    "source_archive": source_archive.name if source_archive else None,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        lines = []
        for path in [report, state, *( [source_archive] if source_archive else [] )]:
            lines.append(f"{self._sha(path)}  {path.name}")
        for path, digest in source_hashes.items():
            lines.append(f"{digest}  {path}")
        sha_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return CheckpointArtifacts(report=report, sha256s=sha_file, state=state, source_archive=source_archive)
