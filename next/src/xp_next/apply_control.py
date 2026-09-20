from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from .isolated_workspace import workspace_changed_paths
from .sandbox_review import (
    ReviewBundle,
    ReviewStatus,
    VerifierSpec,
    build_review_bundle,
    run_verifiers,
)


class ApplyGuardError(RuntimeError):
    pass


class ApplyStatus(str, Enum):
    APPLIED = "APPLIED"
    DISCARDED = "DISCARDED"
    ROLLED_BACK = "ROLLED_BACK"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


@dataclass(frozen=True)
class ApplyResult:
    status: ApplyStatus
    detail: str
    changed_files: tuple[str, ...]
    recovery_ref: str | None
    apply_performed: bool
    rollback_performed: bool
    post_verify_status: str | None = None

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


_MAX_CHANGED_FILES = 50
_MAX_SINGLE_FILE_BYTES = 8 * 1024 * 1024
_MAX_TOTAL_CHANGED_BYTES = 16 * 1024 * 1024


def _git(
    project: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        ["git", "-C", str(project), *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def _head(project: Path) -> str:
    return _git(project, "rev-parse", "HEAD").stdout.strip()


def _require_git_directory(root: Path | str, label: str) -> Path:
    path = Path(root).expanduser().resolve(strict=True)
    if not path.is_dir() or not (path / ".git").exists():
        raise ApplyGuardError(f"{label} must be a Git working tree")
    return path


def _validate_recovery_id(recovery_id: str) -> str:
    value = recovery_id.strip()
    if not value or len(value) > 120:
        raise ApplyGuardError("recovery_id must be non-empty and bounded")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    if any(ch not in allowed for ch in value):
        raise ApplyGuardError("recovery_id contains unsafe characters")
    return value


def _safe_relative(relative: str) -> Path:
    value = Path(relative)
    if (
        not relative
        or value.is_absolute()
        or any(part in {"", ".", ".."} for part in value.parts)
    ):
        raise ApplyGuardError(f"unsafe changed path: {relative!r}")
    return value


def _safe_target(root: Path, relative: str) -> Path:
    rel = _safe_relative(relative)
    current = root
    for part in rel.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ApplyGuardError(f"symlink parent is forbidden: {relative}")
        if current.exists() and not current.is_dir():
            raise ApplyGuardError(f"non-directory parent blocks path: {relative}")
    target = root / rel
    if target.is_symlink():
        raise ApplyGuardError(f"symlink target is forbidden: {relative}")
    return target


def _tracked_bytes(project: Path, head: str, relative: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "-C", str(project), "show", f"{head}:{relative}"],
        check=False,
        capture_output=True,
        timeout=30,
    )
    if proc.returncode == 0:
        return proc.stdout
    return None


def _validate_change_set(
    original: Path,
    sandbox: Path,
    *,
    original_head: str,
    sandbox_head: str,
    changed_files: tuple[str, ...],
) -> None:
    if not changed_files:
        raise ApplyGuardError("review contains no changed files")
    if len(changed_files) > _MAX_CHANGED_FILES:
        raise ApplyGuardError("changed-file count exceeds CP-07A bound")

    total = 0
    for relative in changed_files:
        sandbox_path = _safe_target(sandbox, relative)
        original_path = _safe_target(original, relative)

        sandbox_baseline = _tracked_bytes(sandbox, sandbox_head, relative)
        original_baseline = _tracked_bytes(original, original_head, relative)
        if sandbox_baseline != original_baseline:
            raise ApplyGuardError(
                f"sandbox baseline does not match original HEAD for {relative}"
            )

        if sandbox_path.exists():
            if not sandbox_path.is_file():
                raise ApplyGuardError(
                    f"CP-07A supports regular-file changes only: {relative}"
                )
            size = sandbox_path.stat().st_size
            if size > _MAX_SINGLE_FILE_BYTES:
                raise ApplyGuardError(f"changed file exceeds size bound: {relative}")
            total += size
        elif original_baseline is None:
            raise ApplyGuardError(
                f"changed path is absent in sandbox and original baseline: {relative}"
            )

        if original_path.exists() and not original_path.is_file():
            raise ApplyGuardError(
                f"original changed path is not a regular file: {relative}"
            )

    if total > _MAX_TOTAL_CHANGED_BYTES:
        raise ApplyGuardError("total changed-file bytes exceed CP-07A bound")


def _worktree_fingerprint(project: Path) -> str:
    changed = workspace_changed_paths(project)
    digest = hashlib.sha256()
    digest.update(_head(project).encode("ascii"))
    digest.update(bytes([0]))
    for relative in changed:
        digest.update(relative.encode("utf-8"))
        digest.update(bytes([0]))
        path = _safe_target(project, relative)
        if path.is_file():
            digest.update(b"FILE")
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
        elif path.exists():
            digest.update(b"OTHER")
        else:
            digest.update(b"DELETED")
        digest.update(bytes([0]))
    return digest.hexdigest()


def _require_original_baseline(original: Path, expected_head: str) -> None:
    if _head(original) != expected_head:
        raise ApplyGuardError("original HEAD changed since the approved baseline")
    changed = workspace_changed_paths(original)
    if changed:
        raise ApplyGuardError(
            "original working tree is not clean; Apply refused before mutation"
        )


def _review_is_fresh(
    sandbox: Path,
    approved_review: ReviewBundle,
    verifier_specs: tuple[VerifierSpec, ...],
    *,
    max_diff_chars: int,
) -> ReviewBundle:
    if approved_review.status is not ReviewStatus.PASS:
        raise ApplyGuardError("only PASS review bundles can be applied")
    if approved_review.diff_truncated:
        raise ApplyGuardError("truncated review cannot be applied")

    current = build_review_bundle(
        sandbox,
        verifier_specs=verifier_specs,
        max_diff_chars=max_diff_chars,
    )
    if current.status is not ReviewStatus.PASS:
        raise ApplyGuardError("sandbox no longer passes verification")
    if current.diff_truncated:
        raise ApplyGuardError("current sandbox review is truncated")

    checks = (
        current.sandbox_head == approved_review.sandbox_head,
        current.change_fingerprint == approved_review.change_fingerprint,
        current.verifier_spec_fingerprint
        == approved_review.verifier_spec_fingerprint,
        current.changed_files == approved_review.changed_files,
        current.bounded_diff == approved_review.bounded_diff,
    )
    if not all(checks):
        raise ApplyGuardError("sandbox changed after human review")
    return current


def _manifest_path(recovery_ref: Path) -> Path:
    return recovery_ref / "manifest.json"


def _write_manifest(recovery_ref: Path, data: dict[str, object]) -> None:
    recovery_ref.mkdir(parents=False, exist_ok=False, mode=0o700)
    tmp = recovery_ref / "manifest.json.tmp"
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(_manifest_path(recovery_ref))


def _update_manifest(recovery_ref: Path, **changes: object) -> dict[str, object]:
    path = _manifest_path(recovery_ref)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(changes)
    tmp = recovery_ref / "manifest.json.tmp"
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return data


def _create_recovery_point(
    original: Path,
    recovery_parent: Path | str,
    *,
    recovery_id: str,
    original_head: str,
    approved_review: ReviewBundle,
) -> Path:
    parent = Path(recovery_parent).expanduser()
    parent = Path(os.path.abspath(os.fspath(parent)))
    if parent.is_symlink():
        raise ApplyGuardError("recovery parent must not be a symlink")
    try:
        parent.relative_to(original)
    except ValueError:
        pass
    else:
        raise ApplyGuardError("recovery parent must be outside original project")

    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    resolved_parent = parent.resolve(strict=True)
    try:
        resolved_parent.relative_to(original)
    except ValueError:
        pass
    else:
        raise ApplyGuardError("resolved recovery parent must be outside original project")
    parent = resolved_parent
    try:
        parent.chmod(0o700)
    except OSError:
        pass

    recovery_ref = parent / _validate_recovery_id(recovery_id)
    if recovery_ref.exists():
        raise ApplyGuardError("recovery point already exists")

    manifest = {
        "version": 1,
        "state": "CREATED",
        "original_root": str(original),
        "original_head": original_head,
        "original_status": "clean",
        "changed_files": list(approved_review.changed_files),
        "review_change_fingerprint": approved_review.change_fingerprint,
        "review_verifier_spec_fingerprint": approved_review.verifier_spec_fingerprint,
        "applied_worktree_fingerprint": None,
    }
    _write_manifest(recovery_ref, manifest)
    return recovery_ref


def _apply_paths(
    original: Path,
    sandbox: Path,
    changed_files: tuple[str, ...],
) -> None:
    for relative in changed_files:
        source = _safe_target(sandbox, relative)
        target = _safe_target(original, relative)
        if source.exists():
            if not source.is_file():
                raise ApplyGuardError(
                    f"sandbox path is not a regular file: {relative}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            target = _safe_target(original, relative)
            shutil.copy2(source, target)
        else:
            if target.exists():
                if not target.is_file():
                    raise ApplyGuardError(
                        f"cannot delete non-file original path: {relative}"
                    )
                target.unlink()


def _remove_empty_parents(root: Path, path: Path) -> None:
    current = path.parent
    while current != root:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _force_restore_clean_head(original: Path, expected_head: str) -> None:
    if _head(original) != expected_head:
        raise ApplyGuardError("cannot rollback: original HEAD changed")

    changed = workspace_changed_paths(original)
    for relative in changed:
        target = _safe_target(original, relative)
        tracked = _tracked_bytes(original, expected_head, relative) is not None
        if tracked:
            proc = _git(
                original,
                "restore",
                f"--source={expected_head}",
                "--staged",
                "--worktree",
                "--",
                relative,
                check=False,
            )
            if proc.returncode != 0:
                raise ApplyGuardError(
                    f"rollback git restore failed for {relative}: {proc.stderr[:300]}"
                )
        elif target.exists():
            if not target.is_file():
                raise ApplyGuardError(
                    f"rollback refuses non-file untracked path: {relative}"
                )
            target.unlink()
            _remove_empty_parents(original, target)

    if workspace_changed_paths(original):
        raise ApplyGuardError("rollback did not restore a clean original tree")


def _post_apply_verify(
    original: Path,
    approved_review: ReviewBundle,
    verifier_specs: tuple[VerifierSpec, ...],
) -> tuple[bool, str]:
    current_paths = workspace_changed_paths(original)
    if current_paths != approved_review.changed_files:
        return False, "applied changed paths differ from approved review"

    diff_check = _git(original, "diff", "--check", "HEAD", "--", check=False)
    if diff_check.returncode != 0:
        return False, "git diff --check failed after Apply"

    results = run_verifiers(original, verifier_specs)
    if not results:
        return False, "no explicit post-Apply verifier configured"
    failed = [item for item in results if item.status is not ReviewStatus.PASS]
    if failed:
        return False, "; ".join(f"{item.name}: {item.detail}" for item in failed)
    return True, "PASS"


def apply_reviewed_sandbox(
    *,
    original_root: Path | str,
    sandbox_root: Path | str,
    approved_review: ReviewBundle,
    verifier_specs: tuple[VerifierSpec, ...],
    expected_original_head: str,
    recovery_parent: Path | str,
    recovery_id: str,
    max_diff_chars: int = 12_000,
) -> ApplyResult:
    original = _require_git_directory(original_root, "original_root")
    sandbox = _require_git_directory(sandbox_root, "sandbox_root")
    if original == sandbox:
        raise ApplyGuardError("sandbox and original must be different directories")
    if not verifier_specs:
        raise ApplyGuardError("CP-07A requires explicit verifier specs")

    _require_original_baseline(original, expected_original_head)
    fresh = _review_is_fresh(
        sandbox,
        approved_review,
        verifier_specs,
        max_diff_chars=max_diff_chars,
    )
    _validate_change_set(
        original,
        sandbox,
        original_head=expected_original_head,
        sandbox_head=fresh.sandbox_head,
        changed_files=fresh.changed_files,
    )

    recovery_ref = _create_recovery_point(
        original,
        recovery_parent,
        recovery_id=recovery_id,
        original_head=expected_original_head,
        approved_review=fresh,
    )

    apply_started = False
    try:
        apply_started = True
        _apply_paths(original, sandbox, fresh.changed_files)
        ok, detail = _post_apply_verify(original, fresh, verifier_specs)
        if not ok:
            _force_restore_clean_head(original, expected_original_head)
            _update_manifest(
                recovery_ref,
                state="ROLLED_BACK",
                rollback_reason=detail,
                applied_worktree_fingerprint=None,
            )
            return ApplyResult(
                status=ApplyStatus.ROLLED_BACK,
                detail=f"post-Apply verification failed; rollback completed: {detail}",
                changed_files=fresh.changed_files,
                recovery_ref=str(recovery_ref),
                apply_performed=True,
                rollback_performed=True,
                post_verify_status="FAIL",
            )

        applied_fingerprint = _worktree_fingerprint(original)
        _update_manifest(
            recovery_ref,
            state="APPLIED",
            applied_worktree_fingerprint=applied_fingerprint,
        )
        return ApplyResult(
            status=ApplyStatus.APPLIED,
            detail="reviewed sandbox changes applied and verified",
            changed_files=fresh.changed_files,
            recovery_ref=str(recovery_ref),
            apply_performed=True,
            rollback_performed=False,
            post_verify_status="PASS",
        )
    except Exception as exc:
        if apply_started:
            try:
                _force_restore_clean_head(original, expected_original_head)
                _update_manifest(
                    recovery_ref,
                    state="ROLLED_BACK",
                    rollback_reason=f"{type(exc).__name__}: {exc}"[:500],
                    applied_worktree_fingerprint=None,
                )
                return ApplyResult(
                    status=ApplyStatus.ROLLED_BACK,
                    detail=f"Apply failed; rollback completed: {type(exc).__name__}: {exc}"[:700],
                    changed_files=fresh.changed_files,
                    recovery_ref=str(recovery_ref),
                    apply_performed=True,
                    rollback_performed=True,
                    post_verify_status="FAIL",
                )
            except Exception as rollback_exc:
                _update_manifest(
                    recovery_ref,
                    state="NEEDS_ATTENTION",
                    rollback_reason=f"{type(rollback_exc).__name__}: {rollback_exc}"[:500],
                )
                return ApplyResult(
                    status=ApplyStatus.NEEDS_ATTENTION,
                    detail=(
                        "Apply failed and automatic rollback also failed: "
                        f"{type(rollback_exc).__name__}: {rollback_exc}"
                    )[:700],
                    changed_files=fresh.changed_files,
                    recovery_ref=str(recovery_ref),
                    apply_performed=True,
                    rollback_performed=False,
                    post_verify_status="FAIL",
                )
        raise


def discard_reviewed_sandbox(
    *,
    original_root: Path | str,
    sandbox_root: Path | str,
    approved_review: ReviewBundle,
    verifier_specs: tuple[VerifierSpec, ...],
    expected_original_head: str,
    max_diff_chars: int = 12_000,
) -> ApplyResult:
    original = _require_git_directory(original_root, "original_root")
    sandbox = _require_git_directory(sandbox_root, "sandbox_root")
    _require_original_baseline(original, expected_original_head)
    fresh = _review_is_fresh(
        sandbox,
        approved_review,
        verifier_specs,
        max_diff_chars=max_diff_chars,
    )
    return ApplyResult(
        status=ApplyStatus.DISCARDED,
        detail="reviewed sandbox discarded; original remained unchanged",
        changed_files=fresh.changed_files,
        recovery_ref=None,
        apply_performed=False,
        rollback_performed=False,
        post_verify_status=None,
    )


def rollback_recovery(
    *,
    original_root: Path | str,
    recovery_ref: Path | str,
) -> ApplyResult:
    original = _require_git_directory(original_root, "original_root")
    recovery = Path(recovery_ref).expanduser().resolve(strict=True)
    manifest_path = _manifest_path(recovery)
    if not manifest_path.is_file():
        raise ApplyGuardError("recovery manifest is missing")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    if data.get("original_root") != str(original):
        raise ApplyGuardError("recovery point belongs to another original project")
    if data.get("state") != "APPLIED":
        raise ApplyGuardError("recovery point is not in APPLIED state")

    expected_head = str(data.get("original_head", ""))
    if _head(original) != expected_head:
        raise ApplyGuardError("original HEAD changed after Apply; rollback refused")

    expected_fingerprint = data.get("applied_worktree_fingerprint")
    if not isinstance(expected_fingerprint, str) or not expected_fingerprint:
        raise ApplyGuardError("recovery point has no applied worktree fingerprint")
    if _worktree_fingerprint(original) != expected_fingerprint:
        raise ApplyGuardError(
            "original working tree changed after Apply; manual rollback refused"
        )

    changed_files = tuple(str(x) for x in data.get("changed_files", []))
    _force_restore_clean_head(original, expected_head)
    _update_manifest(
        recovery,
        state="ROLLED_BACK",
        rollback_reason="manual rollback",
        applied_worktree_fingerprint=None,
    )
    return ApplyResult(
        status=ApplyStatus.ROLLED_BACK,
        detail="manual rollback restored original HEAD working tree",
        changed_files=changed_files,
        recovery_ref=str(recovery),
        apply_performed=True,
        rollback_performed=True,
        post_verify_status=None,
    )
