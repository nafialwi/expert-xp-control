from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .packages import StagedPackage


class PackageExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionPreflight:
    status: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    changed_paths: tuple[str, ...]
    backup_dir: Path


_FORBIDDEN_EXACT = {".env", ".git", ".git/config", ".git/HEAD"}
_FORBIDDEN_PREFIXES = (".git/",)
_SECRET_NAMES = {"credentials", "credentials.json", "secrets.json", "id_rsa", "id_ed25519"}
_MUTATION_TYPES = {"ADD_FILE", "REPLACE_FILE", "DELETE_ALLOWED_FILE", "APPLY_PATCH"}


def _safe_repo_relative(value: str) -> PurePosixPath:
    if not value or "\\" in value:
        raise PackageExecutionError(f"Invalid repository path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PackageExecutionError(f"Unsafe repository path: {value!r}")
    return path


def _forbidden_target(path: PurePosixPath) -> bool:
    text = str(path)
    if text in _FORBIDDEN_EXACT or any(text.startswith(p) for p in _FORBIDDEN_PREFIXES):
        return True
    if path.name.lower() in _SECRET_NAMES or path.name.lower().startswith(".env"):
        return True
    return False


class PackageExecutor:
    def __init__(self, repo: Path):
        self.repo = Path(repo).resolve()

    def _target(self, relative: str) -> Path:
        safe = _safe_repo_relative(relative)
        if _forbidden_target(safe):
            raise PackageExecutionError(f"Forbidden target: {relative}")
        target = (self.repo / Path(*safe.parts)).resolve()
        if target != self.repo and self.repo not in target.parents:
            raise PackageExecutionError(f"Target escapes repository: {relative}")
        return target

    def _source(self, staged: StagedPackage, relative: str) -> Path:
        safe = _safe_repo_relative(relative)
        source = (staged.root / Path(*safe.parts)).resolve()
        root = staged.root.resolve()
        if source != root and root not in source.parents:
            raise PackageExecutionError(f"Source escapes staged package: {relative}")
        if not source.is_file():
            raise PackageExecutionError(f"Package source does not exist: {relative}")
        return source

    def preflight(self, staged: StagedPackage) -> ExecutionPreflight:
        reasons: list[str] = []
        manifest = staged.manifest
        for op in manifest.operations:
            op_type = str(op.get("type"))
            if op_type not in _MUTATION_TYPES and op_type not in {
                "REGISTER_MIGRATION",
                "RUN_SOURCE_VERIFY",
                "APPLY_DB_MIGRATION",
                "RUN_SQL_TEST",
                "GENERATE_CHECKPOINT",
            }:
                reasons.append(f"operation not executable by XP V2: {op_type}")
                continue
            if op_type in {"ADD_FILE", "REPLACE_FILE", "DELETE_ALLOWED_FILE"}:
                try:
                    target_rel = str(op["path"])
                    target = _safe_repo_relative(target_rel)
                    if _forbidden_target(target):
                        reasons.append(f"forbidden target: {target_rel}")
                        continue
                    if not any(
                        str(target).startswith(prefix.rstrip("/") + "/")
                        or str(target) == prefix.rstrip("/")
                        for prefix in manifest.allowed_paths
                    ):
                        reasons.append(f"target outside package scope: {target_rel}")
                    self._target(target_rel)
                    if op_type in {"ADD_FILE", "REPLACE_FILE"}:
                        self._source(staged, str(op["source"]))
                        if op_type == "ADD_FILE" and self._target(target_rel).exists():
                            reasons.append(f"ADD_FILE target already exists: {target_rel}")
                        if op_type == "REPLACE_FILE" and not self._target(target_rel).is_file():
                            reasons.append(f"REPLACE_FILE target missing: {target_rel}")
                except (KeyError, PackageExecutionError) as exc:
                    reasons.append(str(exc))
            elif op_type == "APPLY_PATCH":
                patch_rel = str(op.get("source", "source.patch"))
                try:
                    patch = self._source(staged, patch_rel)
                except PackageExecutionError as exc:
                    reasons.append(str(exc))
                    continue
                if (self.repo / ".git").exists():
                    result = subprocess.run(
                        ["git", "apply", "--check", str(patch)],
                        cwd=self.repo,
                        text=True,
                        capture_output=True,
                    )
                    if result.returncode != 0:
                        reasons.append("git apply preflight failed")
                else:
                    reasons.append("APPLY_PATCH requires a Git repository")
        return ExecutionPreflight("ERROR" if reasons else "CLEAR", tuple(reasons))

    def _copy_backup(self, target: Path, backup_dir: Path) -> None:
        if not target.exists():
            return
        relative = target.relative_to(self.repo)
        destination = backup_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            shutil.copy2(target, destination)

    def apply(self, staged: StagedPackage, backup_root: Path) -> ExecutionResult:
        report = self.preflight(staged)
        if report.status != "CLEAR":
            raise PackageExecutionError("; ".join(report.reasons))
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = Path(backup_root) / timestamp
        backup_dir.mkdir(parents=True, exist_ok=True)
        changed: list[str] = []
        applied_patches: list[Path] = []
        try:
            for op in staged.manifest.operations:
                op_type = str(op.get("type"))
                if op_type == "ADD_FILE":
                    source = self._source(staged, str(op["source"]))
                    target = self._target(str(op["path"]))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    tmp = target.with_name(target.name + f".xp-{os.getpid()}.tmp")
                    shutil.copy2(source, tmp)
                    os.replace(tmp, target)
                    changed.append(str(target.relative_to(self.repo)))
                elif op_type == "REPLACE_FILE":
                    source = self._source(staged, str(op["source"]))
                    target = self._target(str(op["path"]))
                    self._copy_backup(target, backup_dir)
                    tmp = target.with_name(target.name + f".xp-{os.getpid()}.tmp")
                    shutil.copy2(source, tmp)
                    os.replace(tmp, target)
                    changed.append(str(target.relative_to(self.repo)))
                elif op_type == "DELETE_ALLOWED_FILE":
                    target = self._target(str(op["path"]))
                    self._copy_backup(target, backup_dir)
                    if target.exists():
                        target.unlink()
                    changed.append(str(target.relative_to(self.repo)))
                elif op_type == "APPLY_PATCH":
                    patch = self._source(staged, str(op.get("source", "source.patch")))
                    result = subprocess.run(
                        ["git", "apply", str(patch)],
                        cwd=self.repo,
                        text=True,
                        capture_output=True,
                    )
                    if result.returncode != 0:
                        raise PackageExecutionError(result.stderr.strip() or "git apply failed")
                    applied_patches.append(patch)
                    changed.append("<git-patch>")
                # Non-source operations are intentionally orchestrated by workflow/adapters.
        except Exception:
            # Restore file-based mutations first, then reverse patches. This keeps
            # package application atomic even when a later mutation fails after
            # a patch has already been applied.
            for rel in reversed(changed):
                if rel == "<git-patch>":
                    continue
                target = self.repo / rel
                backup = backup_dir / rel
                if backup.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup, target)
                else:
                    target.unlink(missing_ok=True)
            for patch in reversed(applied_patches):
                subprocess.run(
                    ["git", "apply", "-R", str(patch)],
                    cwd=self.repo,
                    text=True,
                    capture_output=True,
                )
            raise
        return ExecutionResult("CLEAR", tuple(changed), backup_dir)
