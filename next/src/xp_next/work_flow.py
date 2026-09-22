from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shlex

from .project_service import ProjectService
from .sandbox_review import VerifierSpec


class WorkFlowNeedsAttention(RuntimeError):
    """A human-readable preflight condition blocks safe work execution."""


@dataclass(frozen=True)
class WorkPreparation:
    project_id: str
    project_name: str
    project_root: str
    source_head: str
    goal: str
    worker_prompt: str
    verifier: VerifierSpec
    verifier_source: str

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["verifier"] = {
            "name": self.verifier.name,
            "argv": list(self.verifier.argv),
            "timeout_seconds": self.verifier.timeout_seconds,
        }
        return data


def _resolve_project(
    projects: ProjectService,
    project_id: str | None,
) -> dict[str, object]:
    if project_id is not None:
        return projects.store.get_project(project_id)

    active = projects.current()
    if active is not None:
        return active

    listed = projects.list_projects()
    if len(listed) == 1:
        return listed[0]
    if not listed:
        raise WorkFlowNeedsAttention(
            "belum ada project terdaftar; daftarkan project sebelum menjalankan work"
        )
    raise WorkFlowNeedsAttention(
        "ada beberapa project tetapi belum ada project aktif; pilih project lebih dulu"
    )


def verifier_from_command(
    command: str,
    *,
    timeout_seconds: float = 120.0,
) -> VerifierSpec:
    value = str(command).strip()
    if not value:
        raise WorkFlowNeedsAttention("verifier command tidak boleh kosong")
    try:
        argv = tuple(shlex.split(value, posix=True))
    except ValueError as exc:
        raise WorkFlowNeedsAttention(f"verifier command tidak valid: {exc}") from exc
    if not argv:
        raise WorkFlowNeedsAttention("verifier command tidak menghasilkan argv")
    try:
        return VerifierSpec(
            name="work-verifier",
            argv=argv,
            timeout_seconds=timeout_seconds,
        )
    except ValueError as exc:
        raise WorkFlowNeedsAttention(str(exc)) from exc


def discover_project_verifier(
    project_root: Path | str,
    *,
    timeout_seconds: float = 300.0,
) -> VerifierSpec | None:
    """Conservatively discover only an explicit canonical npm verify script."""

    root = Path(project_root).expanduser().resolve(strict=True)
    package_json = root / "package.json"
    if not package_json.is_file():
        return None
    try:
        payload = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    scripts = payload.get("scripts")
    if not isinstance(scripts, dict):
        return None
    verify = scripts.get("verify")
    if not isinstance(verify, str) or not verify.strip():
        return None
    return VerifierSpec(
        name="npm-verify",
        argv=("npm", "run", "verify"),
        timeout_seconds=timeout_seconds,
    )


def prepare_work(
    projects: ProjectService,
    *,
    goal: str,
    project_id: str | None = None,
    worker_prompt: str | None = None,
    verifier_command: str | None = None,
    verifier_timeout: float = 120.0,
) -> WorkPreparation:
    normalized_goal = str(goal).strip()
    if not normalized_goal:
        raise WorkFlowNeedsAttention("jelaskan pekerjaan yang ingin dilakukan")
    if len(normalized_goal) > 12_000:
        raise WorkFlowNeedsAttention("deskripsi pekerjaan melebihi batas 12000 karakter")

    project = _resolve_project(projects, project_id)
    selected_id = str(project["id"])
    inspection = projects.inspect(selected_id)

    if str(project.get("source_kind")) != "git":
        raise WorkFlowNeedsAttention(
            "CP-08H hanya mengizinkan project Git agar Apply memiliki source guard"
        )
    git = dict(inspection.get("git", {}))
    if git.get("inside_work_tree") is not True:
        raise WorkFlowNeedsAttention("project bukan Git worktree yang valid")
    if git.get("dirty") is not False:
        raise WorkFlowNeedsAttention(
            "project harus clean sebelum work dimulai; selesaikan perubahan lokal lebih dulu"
        )
    source_head = str(git.get("head") or "")
    if not source_head:
        raise WorkFlowNeedsAttention("Git HEAD project tidak dapat dibaca")

    if verifier_command is not None:
        verifier = verifier_from_command(
            verifier_command,
            timeout_seconds=verifier_timeout,
        )
        verifier_source = "explicit_cli"
    else:
        verifier = discover_project_verifier(
            str(project["root_path"]),
            timeout_seconds=min(max(verifier_timeout, 1.0), 300.0),
        )
        verifier_source = "package_json_scripts_verify"
        if verifier is None:
            raise WorkFlowNeedsAttention(
                "verifier aman belum terdeteksi; project perlu scripts.verify atau --verify-cmd"
            )

    normalized_prompt = (
        normalized_goal if worker_prompt is None else str(worker_prompt).strip()
    )
    if not normalized_prompt:
        raise WorkFlowNeedsAttention("worker prompt tidak boleh kosong")
    if len(normalized_prompt) > 12_000:
        raise WorkFlowNeedsAttention("worker prompt melebihi batas 12000 karakter")

    return WorkPreparation(
        project_id=selected_id,
        project_name=str(project["name"]),
        project_root=str(project["root_path"]),
        source_head=source_head,
        goal=normalized_goal,
        worker_prompt=normalized_prompt,
        verifier=verifier,
        verifier_source=verifier_source,
    )
