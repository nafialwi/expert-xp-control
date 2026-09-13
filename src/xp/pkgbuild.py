from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from . import __version__
from .adapters.git import GitAdapter
from .packages import RunContext, inspect_package, validate_package
from .paths import XPPaths
from .project_registry import load_project_profile
from .state_store import StateStore
from .schema import SPEC_FILE_OPERATIONS, SPEC_SQL_OPERATIONS, validate_spec_dict

_FILE_OPS = set(SPEC_FILE_OPERATIONS)
_SQL_OPS = set(SPEC_SQL_OPERATIONS)


class SpecError(ValueError):
    pass


def _latest_run(paths: XPPaths, project_id: str):
    if not paths.runs.exists():
        return None
    store = StateStore(paths)
    states = []
    for item in paths.runs.iterdir():
        if not (item / "state.json").is_file():
            continue
        try:
            state = store.load(item.name)
        except Exception:
            continue
        if state.project_id == project_id:
            if state.stage in {"LOCKED_LOCAL", "LOCKED_REMOTE"}:
                continue
            states.append((item.stat().st_mtime, state))
    return max(states, key=lambda x: x[0])[1] if states else None


def build_package_from_spec(home: Path, repo: Path, spec_path: Path, out: Path | None = None) -> Path:
    repo = Path(repo).expanduser().resolve()
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    schema_errors = validate_spec_dict(spec)
    if schema_errors:
        raise SpecError("spec tidak valid: " + "; ".join(schema_errors))
    profile = load_project_profile(repo)
    declared_project = str(spec.get("project_id", "")).strip()
    if declared_project and declared_project != profile.project_id:
        raise SpecError(
            f"project_id mismatch: spec={declared_project}, profile={profile.project_id}"
        )
    paths = XPPaths.from_home(home)
    run = _latest_run(paths, profile.project_id)
    stage = run.stage if run else "IDLE"
    package_type = str(spec.get("package_type", "WORK"))
    if package_type not in {"WORK", "REMEDIATION"}:
        raise SpecError("package_type harus WORK atau REMEDIATION")
    git = GitAdapter(repo)
    base_fingerprint = git.working_fingerprint()

    operations: list[dict[str, Any]] = []
    members: dict[str, bytes] = {}
    checksums: dict[str, str] = {}
    counter = 0

    def add_member(rel: str, data: bytes) -> str:
        nonlocal counter
        counter += 1
        member = f"payload/{counter:04d}_{rel.replace('/', '__')}"
        members[member] = data
        checksums[member] = hashlib.sha256(data).hexdigest()
        return member

    declared_sql: dict[str, str] = {}
    for op in spec.get("operations", []):
        op_type = str(op.get("type"))
        if op_type in _FILE_OPS or op_type in _SQL_OPS:
            rel = str(op["path"])
            content = op.get("content")
            if content is None:
                raise SpecError(f"operation {op_type} membutuhkan 'content': {rel}")
            data = content.encode("utf-8")
            exists = (repo / rel).is_file()
            file_op = "REPLACE_FILE" if exists else "ADD_FILE"
            member = add_member(rel, data)
            operations.append({"type": file_op, "path": rel, "source": member})
            if op_type in _SQL_OPS:
                declared_sql[rel] = op_type
        elif op_type == "DELETE_ALLOWED_FILE":
            operations.append({"type": op_type, "path": str(op["path"])})
        elif op_type == "APPLY_PATCH":
            patch_text = op.get("patch") or op.get("content")
            if not patch_text:
                raise SpecError("APPLY_PATCH membutuhkan 'patch' (unified diff)")
            member = add_member("patch.diff", patch_text.encode("utf-8"))
            operations.append({"type": "APPLY_PATCH", "source": member})
        else:
            raise SpecError(f"operation tidak didukung pkg-build: {op_type}")
    for rel, sql_type in declared_sql.items():
        operations.append({"type": sql_type, "path": rel})

    allowed_paths = [str(v) for v in spec.get("allowed_paths", [])]
    if not allowed_paths:
        raise SpecError("spec wajib mendeklarasikan allowed_paths (scope tujuan)")
    manifest: dict[str, Any] = {
        "protocol_version": 1,
        "min_xp_version": __version__,
        "package_type": package_type,
        "project_id": profile.project_id,
        "run_id": spec.get("run_id"),
        "milestone": spec.get("milestone"),
        "base_fingerprint": base_fingerprint,
        "expected_state": str(spec.get("expected_state") or stage),
        "allowed_paths": allowed_paths,
        "operations": operations,
        "checksums": checksums,
        "human_qa": [str(v) for v in spec.get("human_qa", [])],
    }
    if package_type == "REMEDIATION":
        if not run or run.stage != "WAITING_GPT":
            raise SpecError("REMEDIATION hanya valid saat ada incident aktif (WAITING_GPT)")
        manifest["run_id"] = run.run_id
        manifest["incident_id"] = run.metadata.get("incident_id")
        manifest["incident_challenge"] = run.metadata.get("incident_challenge")

    if out is None:
        out_dir = home / "storage" / "downloads" / "Expert"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"XP_PKG_{package_type}_{profile.project_id}_{manifest['milestone'] or 'work'}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
        for member, data in members.items():
            zf.writestr(member, data)

    context = RunContext(
        project_id=profile.project_id,
        stage=stage,
        base_fingerprint=base_fingerprint,
        run_id=run.run_id if run else None,
        incident_id=run.metadata.get("incident_id") if run else None,
        incident_challenge=run.metadata.get("incident_challenge") if run else None,
    )
    report = validate_package(inspect_package(out), context)
    if report.status != "CLEAR":
        raise SpecError("validasi paket gagal: " + "; ".join(report.reasons))
    return out
