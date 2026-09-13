#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from xp.adapters.postgresql import PostgreSQLAdapter
from xp.autopilot import AutopilotController
from xp.bundle import BundleBuilder
from xp.config import XPConfig
from xp.pkgbuild import build_package_from_spec
from xp.project_context import ProjectSessionResolver
from xp.project_doctor import ProjectDoctor
from xp.project_registry import ProjectRegistry, load_project_profile


SENSITIVE_PRODUCTION_ENV = (
    "DATABASE_URL",
    "PGHOST",
    "PGPORT",
    "PGUSER",
    "PGPASSWORD",
    "PGDATABASE",
    "SUPABASE_ACCESS_TOKEN",
    "SUPABASE_DB_PASSWORD",
    "FIREBASE_TOKEN",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_API_KEY",
    "VERCEL_TOKEN",
    "NETLIFY_AUTH_TOKEN",
)

_ORIGINAL_REPOS: tuple[Path, ...] = ()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def install_original_repo_guard(*repos: Path) -> None:
    global _ORIGINAL_REPOS
    _ORIGINAL_REPOS = tuple(
        Path(repo).expanduser().resolve()
        for repo in repos
    )


def _assert_command_not_in_original(cwd: Path | None) -> None:
    if cwd is None:
        return
    resolved = Path(cwd).expanduser().resolve()
    for original in _ORIGINAL_REPOS:
        if _is_within(resolved, original):
            raise RuntimeError(
                "ZONE1 VIOLATION: subprocess/project command attempted "
                f"inside original repository: {resolved}"
            )


def run(cmd, *, cwd=None, check=True, env=None):
    _assert_command_not_in_original(Path(cwd) if cwd is not None else None)
    result = subprocess.run(
        [str(x) for x in cmd],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or "command failed"
        )
    return result


def git(repo, *args, check=True):
    return run(
        ["git", *args],
        cwd=Path(repo),
        check=check,
    )


def _hash_regular_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _entry_descriptor(path: Path) -> tuple[str, str, int]:
    st = path.lstat()
    mode = st.st_mode
    if stat.S_ISLNK(mode):
        target = os.readlink(path)
        return (
            "L",
            hashlib.sha256(
                target.encode("utf-8", errors="surrogateescape")
            ).hexdigest(),
            len(target),
        )
    if stat.S_ISREG(mode):
        return ("F", _hash_regular_file(path), st.st_size)
    return (
        "S",
        hashlib.sha256(
            f"{mode}:{st.st_rdev}".encode("utf-8")
        ).hexdigest(),
        0,
    )


def full_tree_byte_snapshot(root: Path) -> dict[str, object]:
    """ZONE 1 proof: hash every filesystem entry, including .git/ignored.

    Only plain Python file reads/lstat/readlink are used. No Git command or
    project interpreter is invoked in the original repository.
    """
    root = Path(root).expanduser().resolve()
    digest = hashlib.sha256()
    file_count = 0
    dir_count = 0
    symlink_count = 0

    stack = [root]
    while stack:
        current = stack.pop()
        entries = sorted(
            os.scandir(current),
            key=lambda entry: entry.name,
            reverse=True,
        )
        for entry in entries:
            path = Path(entry.path)
            rel = path.relative_to(root).as_posix()

            if entry.is_symlink():
                kind, content_hash, size = _entry_descriptor(path)
                digest.update(
                    f"{kind}\0{rel}\0{content_hash}\0{size}\n".encode(
                        "utf-8", errors="surrogateescape"
                    )
                )
                symlink_count += 1
                continue

            if entry.is_dir(follow_symlinks=False):
                digest.update(
                    f"D\0{rel}\n".encode(
                        "utf-8", errors="surrogateescape"
                    )
                )
                dir_count += 1
                stack.append(path)
                continue

            kind, content_hash, size = _entry_descriptor(path)
            digest.update(
                f"{kind}\0{rel}\0{content_hash}\0{size}\n".encode(
                    "utf-8", errors="surrogateescape"
                )
            )
            file_count += 1

    return {
        "zone": 1,
        "root": str(root),
        "tree_sha256": digest.hexdigest(),
        "file_count": file_count,
        "directory_count": dir_count,
        "symlink_count": symlink_count,
    }


def assert_zone1_unchanged(
    before: dict[str, object],
    after: dict[str, object],
    label: str,
) -> dict[str, object]:
    keys = (
        "tree_sha256",
        "file_count",
        "directory_count",
        "symlink_count",
    )
    mismatches = {
        key: (before.get(key), after.get(key))
        for key in keys
        if before.get(key) != after.get(key)
    }
    if mismatches:
        raise RuntimeError(
            f"ZONE1 VIOLATION {label}: original full-tree bytes changed: "
            f"{mismatches}"
        )
    return {
        "zone": 1,
        "label": label,
        "before_sha256": before["tree_sha256"],
        "after_sha256": after["tree_sha256"],
        "file_count": before["file_count"],
        "directory_count": before["directory_count"],
        "symlink_count": before["symlink_count"],
        "match": True,
        "command_execution_inside_original": False,
    }


def _copy_project_tree(source: Path, target: Path) -> Path:
    """Make a physical temp copy with no hard-linked regular files."""
    source = Path(source).expanduser().resolve()
    target = Path(target).expanduser().resolve()

    shutil.copytree(
        source,
        target,
        symlinks=True,
        copy_function=shutil.copy2,
        ignore_dangling_symlinks=True,
    )

    # Sanity check representative regular files are physically distinct.
    for rel in (
        ".git/HEAD",
        ".xp/project.json",
        "package.json",
        "README.md",
    ):
        src = source / rel
        dst = target / rel
        if (
            src.is_file()
            and not src.is_symlink()
            and dst.is_file()
            and not dst.is_symlink()
        ):
            src_stat = src.stat()
            dst_stat = dst.stat()
            if (
                src_stat.st_dev == dst_stat.st_dev
                and src_stat.st_ino == dst_stat.st_ino
            ):
                raise RuntimeError(
                    "ZONE1 VIOLATION: temp copy unexpectedly shares "
                    f"a hard link with original: {rel}"
                )

    # Preserved symlinks must never point back into either original repo.
    for path in target.rglob("*"):
        if not path.is_symlink():
            continue
        try:
            resolved = path.resolve(strict=False)
        except OSError:
            continue
        for original in _ORIGINAL_REPOS:
            if _is_within(resolved, original):
                raise RuntimeError(
                    "ZONE1 VIOLATION: temp copy contains a symlink back "
                    f"into original repo: {path.relative_to(target)}"
                )
    return target


def _canonical_dirty_paths(repo: Path) -> set[str]:
    tracked = set(
        filter(
            None,
            git(
                repo,
                "diff",
                "--name-only",
                "HEAD",
                "--",
            ).stdout.splitlines(),
        )
    )
    untracked = set(
        filter(
            None,
            git(
                repo,
                "ls-files",
                "--others",
                "--exclude-standard",
            ).stdout.splitlines(),
        )
    )
    return tracked | untracked


def prepare_acceptance_copy(source: Path, target: Path) -> Path:
    """ZONE 2 copy bootstrap.

    The full live working tree is copied, including .git and ignored artifacts.
    If the live copy carries current .xp metadata outside HEAD, only .xp is
    frozen into an acceptance-only baseline commit. Any canonical dirtiness
    outside .xp is a hard stop.
    """
    target = _copy_project_tree(source, target)
    ensure_git_identity(target)

    dirty = _canonical_dirty_paths(target)
    outside_xp = sorted(
        rel
        for rel in dirty
        if not (
            rel == ".xp"
            or rel.startswith(".xp/")
        )
    )
    if outside_xp:
        raise RuntimeError(
            "ZONE2 bootstrap refused canonical dirtiness outside .xp: "
            + ", ".join(outside_xp)
        )

    xp_dir = target / ".xp"
    if xp_dir.is_dir():
        git(target, "add", "-f", ".xp")
        staged = git(
            target,
            "diff",
            "--cached",
            "--quiet",
            check=False,
        )
        if staged.returncode != 0:
            git(
                target,
                "commit",
                "-m",
                "test(xp+): freeze live XP metadata for A+ acceptance copy",
            )

    residual = _canonical_dirty_paths(target)
    if residual:
        raise RuntimeError(
            "ZONE2 bootstrap did not reach a clean canonical boundary: "
            + ", ".join(sorted(residual))
        )
    return target


def ensure_git_identity(repo):
    git(repo, "config", "user.email", "xp07@example.invalid")
    git(repo, "config", "user.name", "XP+ Acceptance")


def _hash_path_for_boundary(repo: Path, rel: str) -> dict[str, object]:
    path = repo / rel
    if not path.exists() and not path.is_symlink():
        return {"kind": "MISSING"}
    kind, digest, size = _entry_descriptor(path)
    return {
        "kind": kind,
        "sha256": digest,
        "size": size,
    }


def _nonignored_untracked(repo: Path) -> dict[str, dict[str, object]]:
    raw = git(
        repo,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    ).stdout
    paths = [value for value in raw.split("\0") if value]
    return {
        rel: _hash_path_for_boundary(repo, rel)
        for rel in sorted(paths)
    }


def _xp_snapshot(repo: Path) -> dict[str, object]:
    xp = repo / ".xp"
    if not xp.exists():
        return {
            "tree_sha256": hashlib.sha256(b"NO_XP").hexdigest(),
            "file_count": 0,
            "directory_count": 0,
            "symlink_count": 0,
        }
    snap = full_tree_byte_snapshot(xp)
    return {
        "tree_sha256": snap["tree_sha256"],
        "file_count": snap["file_count"],
        "directory_count": snap["directory_count"],
        "symlink_count": snap["symlink_count"],
    }


def _ignored_inventory(repo: Path) -> dict[str, tuple[object, ...]]:
    """Informational only; signatures locate ignored changes efficiently."""
    raw = git(
        repo,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "-z",
    ).stdout
    paths = [value for value in raw.split("\0") if value]
    inventory: dict[str, tuple[object, ...]] = {}
    for rel in sorted(paths):
        path = repo / rel
        try:
            st = path.lstat()
        except FileNotFoundError:
            continue
        if path.is_symlink():
            inventory[rel] = (
                "L",
                os.readlink(path),
                st.st_mtime_ns,
            )
        elif path.is_file():
            inventory[rel] = (
                "F",
                st.st_size,
                st.st_mtime_ns,
            )
        elif path.is_dir():
            inventory[rel] = (
                "D",
                st.st_mtime_ns,
            )
        else:
            inventory[rel] = (
                "S",
                st.st_mode,
                st.st_mtime_ns,
            )
    return inventory


def zone2_canonical_snapshot(repo: Path) -> dict[str, object]:
    """XP canonical source boundary + explicit .xp + ignored info."""
    repo = Path(repo).resolve()
    diff = git(
        repo,
        "diff",
        "--binary",
        "HEAD",
        "--",
    ).stdout
    return {
        "zone": 2,
        "head": git(
            repo,
            "rev-parse",
            "HEAD",
        ).stdout.strip(),
        "tracked_diff_sha256": hashlib.sha256(
            diff.encode("utf-8", errors="surrogateescape")
        ).hexdigest(),
        "nonignored_untracked": _nonignored_untracked(repo),
        "xp": _xp_snapshot(repo),
        "ignored": _ignored_inventory(repo),
    }


def _ignore_rule(repo: Path, rel: str) -> str:
    result = git(
        repo,
        "check-ignore",
        "-v",
        "--",
        rel,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "ZONE2 VIOLATION: informational ignored change is not "
            f"actually covered by Git ignore rules: {rel}"
        )
    return result.stdout.strip()


def assert_zone2_unchanged(
    before: dict[str, object],
    after: dict[str, object],
    repo: Path,
    label: str,
    *,
    expect_head_unchanged: bool = True,
) -> dict[str, object]:
    violations: dict[str, object] = {}

    if expect_head_unchanged and before["head"] != after["head"]:
        violations["head"] = (
            before["head"],
            after["head"],
        )
    if (
        before["tracked_diff_sha256"]
        != after["tracked_diff_sha256"]
    ):
        violations["tracked_diff"] = (
            before["tracked_diff_sha256"],
            after["tracked_diff_sha256"],
        )
    if (
        before["nonignored_untracked"]
        != after["nonignored_untracked"]
    ):
        violations["nonignored_untracked"] = True
    if before["xp"] != after["xp"]:
        violations["xp"] = (
            before["xp"],
            after["xp"],
        )

    if violations:
        raise RuntimeError(
            f"ZONE2 VIOLATION {label}: canonical source boundary changed: "
            f"{violations}"
        )

    before_ignored = dict(before["ignored"])
    after_ignored = dict(after["ignored"])
    changed_ignored = sorted(
        rel
        for rel in (
            set(before_ignored)
            | set(after_ignored)
        )
        if before_ignored.get(rel) != after_ignored.get(rel)
    )
    ignore_rules = {
        rel: _ignore_rule(repo, rel)
        for rel in changed_ignored
    }

    return {
        "zone": 2,
        "label": label,
        "head_unchanged": True,
        "tracked_diff_unchanged": True,
        "nonignored_untracked_unchanged": True,
        "xp_unchanged": True,
        "canonical_boundary_unchanged": True,
        "ignored_changes": changed_ignored,
        "ignored_change_count": len(changed_ignored),
        "ignored_rules": ignore_rules,
        "harness_added_exclusions": [],
    }


def replace_source_remote(repo, root):
    git(repo, "remote", "remove", "origin", check=False)
    bare = Path(root) / f"{Path(repo).name}-safe-origin.git"
    run(["git", "init", "--bare", str(bare)])
    git(repo, "remote", "add", "origin", str(bare))
    branch = (
        git(
            repo,
            "branch",
            "--show-current",
        ).stdout.strip()
        or "seed"
    )
    git(
        repo,
        "push",
        "-u",
        "origin",
        f"HEAD:{branch}",
    )
    url = git(
        repo,
        "remote",
        "get-url",
        "origin",
    ).stdout.strip()
    if not Path(url).resolve().is_relative_to(
        Path(root).resolve()
    ):
        raise RuntimeError(
            "production remote was not replaced by local temp remote"
        )
    return bare


def setup_control_repo(root, home):
    bare = Path(root) / "control-origin.git"
    work = Path(root) / "control"
    run(["git", "init", "--bare", str(bare)])
    run(["git", "clone", str(bare), str(work)])
    ensure_git_identity(work)
    (work / "README.md").write_text(
        "XP+ local A+ acceptance control\n",
        encoding="utf-8",
    )
    git(work, "add", ".")
    git(work, "commit", "-m", "init control")
    git(work, "push", "-u", "origin", "HEAD")
    XPConfig.for_home(home).set_control_repo(work)
    return work


@contextmanager
def production_call_guard():
    old = {
        key: os.environ.get(key)
        for key in SENSITIVE_PRODUCTION_ENV
    }
    for key in SENSITIVE_PRODUCTION_ENV:
        os.environ.pop(key, None)

    events = []

    def blocked_apply(*args, **kwargs):
        events.append("postgres.apply_file")
        raise AssertionError(
            "production DB apply forbidden by XP+-07 A+ smoke"
        )

    def blocked_test(*args, **kwargs):
        events.append("postgres.run_test_file")
        raise AssertionError(
            "production DB test forbidden by XP+-07 A+ smoke"
        )

    with patch.object(
        PostgreSQLAdapter,
        "apply_file",
        blocked_apply,
    ), patch.object(
        PostgreSQLAdapter,
        "run_test_file",
        blocked_test,
    ):
        try:
            yield events
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def assert_deploy_disabled(repo):
    profile = load_project_profile(repo)
    policies = json.loads(
        (Path(repo) / ".xp/policies.json").read_text(
            encoding="utf-8"
        )
    )
    deployment = dict(
        policies.get("deployment") or {}
    )
    if profile.deployment_adapter is not None:
        raise RuntimeError(
            "deployment adapter must be disabled in real-project smoke"
        )
    if (
        str(
            deployment.get("production")
            or "DISABLED"
        )
        != "DISABLED"
    ):
        raise RuntimeError(
            "production deployment policy is not DISABLED"
        )


def empty_work_package(home, repo, milestone):
    profile = load_project_profile(repo)
    spec = (
        Path(home)
        / f"{profile.project_id}-{milestone}.json"
    )
    spec.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    spec.write_text(
        json.dumps(
            {
                "spec_version": "1.0",
                "package_type": "WORK",
                "project_id": profile.project_id,
                "milestone": milestone,
                "allowed_paths": ["acceptance"],
                "operations": [],
                "human_qa": [
                    "A+ read-only acceptance smoke"
                ],
            }
        ),
        encoding="utf-8",
    )
    return build_package_from_spec(
        home,
        repo,
        spec,
    )


def protected_branch_rejection(
    controller,
    repo,
    package,
):
    git(
        repo,
        "switch",
        "-C",
        "main",
        "HEAD",
    )
    before = zone2_canonical_snapshot(repo)
    result = controller.run_package(
        repo,
        package,
    )
    after = zone2_canonical_snapshot(repo)
    zone2 = assert_zone2_unchanged(
        before,
        after,
        repo,
        "protected-branch rejection",
        expect_head_unchanged=True,
    )
    if result.status == "CLEAR":
        raise RuntimeError(
            "protected branch unexpectedly accepted WORK package"
        )
    return {
        "status": result.status,
        "stage": result.stage,
        "handoff": bool(result.handoff),
        "zone2": zone2,
    }


def work_branch_lock_flow(
    controller,
    repo,
    package,
    branch,
):
    git(
        repo,
        "switch",
        "-C",
        branch,
        "HEAD",
    )
    git(
        repo,
        "push",
        "-u",
        "origin",
        branch,
    )
    baseline = zone2_canonical_snapshot(repo)

    result = controller.run_package(
        repo,
        package,
    )
    if (
        result.status != "CLEAR"
        or result.stage != "HUMAN_QA"
    ):
        raise RuntimeError(
            "read-only WORK package did not reach HUMAN_QA: "
            f"{result.status}/{result.stage} {result.message}"
        )

    qa = controller.record_human_qa(
        repo,
        result.run_id,
        clear=True,
        notes="XP+-07 A+ read-only smoke",
    )
    if qa.stage != "READY_TO_LOCK":
        raise RuntimeError(
            "Human QA was not recorded"
        )

    locked = controller.final_lock(
        repo,
        result.run_id,
        approved=True,
    )
    if locked.status != "CLEAR":
        raise RuntimeError(
            f"Final Lock failed: {locked.message}"
        )

    after = zone2_canonical_snapshot(repo)
    zone2 = assert_zone2_unchanged(
        baseline,
        after,
        repo,
        "WORK + verify + Human QA + Final Lock",
        expect_head_unchanged=True,
    )

    state = controller.state_store.load(
        result.run_id
    )
    checkpoint = Path(
        state.metadata["checkpoint_dir"]
    )
    required = (
        checkpoint
        / "CHECKPOINT_STATE.json",
        checkpoint / "SOURCE.zip",
        checkpoint / "SHA256SUMS.txt",
    )
    if not all(
        path.is_file()
        for path in required
    ):
        raise RuntimeError(
            "checkpoint/source archive/hash evidence incomplete"
        )

    return {
        "run_id": result.run_id,
        "locked_stage": locked.stage,
        "checkpoint": True,
        "source_archive": True,
        "hashes": True,
        "human_qa": True,
        "remote_safepoint": state.metadata.get(
            "remote_safepoint"
        ),
        "lease_release": state.metadata.get(
            "remote_lease_release",
            "NOT_REQUIRED",
        ),
        "zone2": zone2,
    }


def _assert_safe_verify_scripts(repo):
    package = json.loads(
        (Path(repo) / "package.json").read_text(
            encoding="utf-8"
        )
    )
    scripts = dict(
        package.get("scripts") or {}
    )
    verify = str(
        scripts.get("verify") or ""
    )
    if not verify:
        raise RuntimeError(
            "Next npm verify script missing"
        )

    forbidden = (
        "firebase deploy",
        "wrangler",
        "supabase db",
        "psql ",
        "curl ",
        "wget ",
        "ssh ",
        "gh ",
        "vercel ",
        "netlify ",
    )
    for name, value in scripts.items():
        lowered = f" {str(value).lower()} "
        if any(
            token in lowered
            for token in forbidden
        ):
            raise RuntimeError(
                "npm script contains production-risk command: "
                f"{name}={value}"
            )
    return verify


def smoke_legacy(
    copy: Path,
    real_home: Path,
    root: Path,
):
    home = root / "legacy-home"
    control = setup_control_repo(
        root / "legacy-control-root",
        home,
    )

    assert_deploy_disabled(copy)
    profile = load_project_profile(copy)
    if profile.profile_version != 1:
        raise RuntimeError(
            "Legacy profile_version is not 1"
        )

    doctor = ProjectDoctor(home).inspect(copy)
    if (
        doctor.status
        != "PROFILE_INCOMPLETE"
    ):
        raise RuntimeError(
            "Legacy doctor expected PROFILE_INCOMPLETE, "
            f"got {doctor.status}"
        )
    recommendations = [
        finding.recommendation
        for finding in doctor.findings
        if finding.recommendation
    ]
    if not recommendations:
        raise RuntimeError(
            "Legacy corrective recommendation missing"
        )

    if profile.database_adapter == "postgresql":
        raise RuntimeError(
            "Legacy was incorrectly forced to PostgreSQL"
        )
    if (
        importlib.util.find_spec(
            "xp.adapters.firebase"
        )
        is not None
    ):
        raise RuntimeError(
            "Firebase is hardcoded as an engine adapter"
        )

    work_branch = (
        "work/xp07-legacy-smoke"
    )
    git(
        copy,
        "switch",
        "-C",
        work_branch,
        "HEAD",
    )
    package = empty_work_package(
        home,
        copy,
        "XP07-LEGACY-SMOKE",
    )
    controller = AutopilotController(home)

    with production_call_guard() as events:
        protected = (
            protected_branch_rejection(
                controller,
                copy,
                package,
            )
        )
        flow = work_branch_lock_flow(
            controller,
            copy,
            package,
            work_branch,
        )
    if events:
        raise RuntimeError(
            f"production DB method called: {events}"
        )
    if not protected["handoff"]:
        raise RuntimeError(
            "Legacy protected-branch failure "
            "produced no recovery handoff"
        )

    lease_file = (
        control
        / "leases"
        / f"{profile.project_id}.json"
    )
    if lease_file.exists():
        raise RuntimeError(
            "Legacy local acceptance lease "
            "was not released"
        )

    return {
        "profile_v1": True,
        "doctor_status": doctor.status,
        "corrective_recommendation": True,
        "firebase_project_concern": True,
        "work_package_on_work_branch": True,
        "protected_branch_rejected": True,
        "checkpoint_recovery_evidence": True,
        "rollback_safety": (
            "covered_by_fixture_regression"
        ),
        "production_db_deploy_calls": 0,
        "protected_zone2": protected["zone2"],
        **flow,
    }


def _history_snapshot(
    paths: list[Path],
) -> dict[str, tuple[str, int, int]]:
    return {
        str(path): (
            _hash_regular_file(path),
            path.stat().st_mtime_ns,
            path.stat().st_size,
        )
        for path in paths
    }


def smoke_next(
    copy: Path,
    real_home: Path,
    root: Path,
):
    actual_checkpoints = (
        Path(real_home)
        / ".expert-workstation"
        / "checkpoints"
        / "segeran-jiwa-pos-next"
    )
    checkpoint_states = sorted(
        actual_checkpoints.glob(
            "*/CHECKPOINT_STATE.json"
        )
    )
    if not checkpoint_states:
        raise RuntimeError(
            "Next checkpoint history missing"
        )

    actual_runs = (
        Path(real_home)
        / ".expert-workstation"
        / "runs"
    )
    locked_remote: list[Path] = []
    for state_path in actual_runs.glob(
        "*/state.json"
    ):
        try:
            raw = json.loads(
                state_path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            continue
        if (
            raw.get("project_id")
            == "segeran-jiwa-pos-next"
            and raw.get("stage")
            == "LOCKED_REMOTE"
        ):
            locked_remote.append(
                state_path
            )
    if not locked_remote:
        raise RuntimeError(
            "Next LOCKED_REMOTE history missing"
        )

    history_paths = [
        *checkpoint_states,
        *locked_remote,
    ]
    before_history = _history_snapshot(
        history_paths
    )

    home = root / "next-home"
    control = setup_control_repo(
        root / "next-control-root",
        home,
    )

    assert_deploy_disabled(copy)
    profile = load_project_profile(copy)
    if profile.profile_version != 1:
        raise RuntimeError(
            "Next profile_version is not 1"
        )
    if (
        profile.database_adapter
        != "postgresql"
    ):
        raise RuntimeError(
            "Next PostgreSQL adapter behavior "
            "was not preserved"
        )

    doctor = ProjectDoctor(home).inspect(
        copy
    )
    if doctor.status != "WORK_READY":
        raise RuntimeError(
            "Next expected WORK_READY, "
            f"got {doctor.status}"
        )

    _assert_safe_verify_scripts(copy)

    postgres = PostgreSQLAdapter()
    readiness = postgres.readiness()
    if (
        "postgresql-environment"
        not in readiness.capabilities
    ):
        raise RuntimeError(
            "PostgreSQL adapter capabilities changed"
        )

    work_branch = (
        "work/xp07-next-smoke"
    )
    git(
        copy,
        "switch",
        "-C",
        work_branch,
        "HEAD",
    )
    package = empty_work_package(
        home,
        copy,
        "XP07-NEXT-SMOKE",
    )
    controller = AutopilotController(home)

    with production_call_guard() as events:
        protected = (
            protected_branch_rejection(
                controller,
                copy,
                package,
            )
        )
        flow = work_branch_lock_flow(
            controller,
            copy,
            package,
            work_branch,
        )
    if events:
        raise RuntimeError(
            f"production DB method called: {events}"
        )

    lease_file = (
        control
        / "leases"
        / f"{profile.project_id}.json"
    )
    if lease_file.exists():
        raise RuntimeError(
            "Next local acceptance lease "
            "was not released"
        )

    after_history = _history_snapshot(
        history_paths
    )
    if before_history != after_history:
        raise RuntimeError(
            "Next checkpoint/run history mutated"
        )

    return {
        "profile_v1": True,
        "postgresql_adapter": True,
        "npm_verify": True,
        "branch_guard": (
            protected["status"]
            != "CLEAR"
        ),
        "checkpoint_history": len(
            checkpoint_states
        ),
        "locked_remote_runs": len(
            locked_remote
        ),
        "new_work_package": True,
        "db_approval_flow": (
            "covered_by_node_postgres_fixture"
        ),
        "remote_safepoint": True,
        "human_qa": True,
        "final_lock": True,
        "remote_lease_released": True,
        "source_archive_hashes": True,
        "production_db_deploy_calls": 0,
        "protected_zone2": protected["zone2"],
        **flow,
    }


def backfill(
    real_home: Path,
    legacy_copy: Path,
    next_copy: Path,
    root: Path,
):
    """Re-prove XP+-03 / 03.5 / 04 entirely on temp copies."""
    home = root / "backfill-home"

    registry = ProjectRegistry.for_home(home)
    legacy_profile = load_project_profile(
        legacy_copy
    )
    next_profile = load_project_profile(
        next_copy
    )
    registry.register(
        legacy_profile,
        legacy_copy,
    )
    registry.register(
        next_profile,
        next_copy,
    )

    legacy_doctor = ProjectDoctor(
        home
    ).inspect(legacy_copy)
    next_doctor = ProjectDoctor(
        home
    ).inspect(next_copy)

    if (
        legacy_doctor.status
        != "PROFILE_INCOMPLETE"
    ):
        raise RuntimeError(
            "XP+-03 backfill Legacy "
            "status mismatch"
        )
    if (
        next_doctor.status
        != "WORK_READY"
    ):
        raise RuntimeError(
            "XP+-03 backfill Next "
            "status mismatch"
        )

    registry_path = (
        Path(home)
        / ".expert-workstation"
        / "registry.json"
    )
    registry_before = (
        registry_path.read_bytes()
        if registry_path.is_file()
        else b""
    )

    session_legacy = (
        ProjectSessionResolver(
            home
        ).resolve(legacy_copy)
    )
    session_next = (
        ProjectSessionResolver(
            home
        ).resolve(next_copy)
    )

    if (
        session_legacy.source != "cwd"
        or session_legacy.project.project_id
        != "segeran-jiwa-pos-legacy"
    ):
        raise RuntimeError(
            "XP+-03.5 Legacy cwd "
            "selection mismatch"
        )
    if (
        session_next.source != "cwd"
        or session_next.project.project_id
        != "segeran-jiwa-pos-next"
    ):
        raise RuntimeError(
            "XP+-03.5 Next cwd "
            "selection mismatch"
        )

    registry_after = (
        registry_path.read_bytes()
        if registry_path.is_file()
        else b""
    )
    if registry_before != registry_after:
        raise RuntimeError(
            "XP+-03.5 cwd selection "
            "mutated last_active registry"
        )

    real_registry = (
        Path(real_home)
        / ".expert-workstation"
        / "registry.json"
    )
    real_registry_before = (
        real_registry.read_bytes()
        if real_registry.is_file()
        else b""
    )

    ratios: dict[str, float] = {}
    bundle_zone2: dict[str, object] = {}
    out = root / "bundle-backfill"
    out.mkdir(
        parents=True,
        exist_ok=True,
    )

    for name, repo in (
        ("Legacy", legacy_copy),
        ("Next", next_copy),
    ):
        before = zone2_canonical_snapshot(
            repo
        )
        builder = BundleBuilder(real_home)
        deep = builder.build(
            repo,
            deep=True,
            output_dir=out / name,
        )
        compact = builder.build(
            repo,
            deep=False,
            output_dir=out / name,
        )
        ratio = (
            compact.size_bytes
            / deep.size_bytes
        )
        if ratio >= 0.35:
            raise RuntimeError(
                f"XP+-04 {name} bundle ratio "
                f"{ratio:.4f} >= 0.35"
            )
        after = zone2_canonical_snapshot(
            repo
        )
        bundle_zone2[name] = (
            assert_zone2_unchanged(
                before,
                after,
                repo,
                f"XP+-04 {name} bundle",
                expect_head_unchanged=True,
            )
        )
        ratios[name] = ratio

    real_registry_after = (
        real_registry.read_bytes()
        if real_registry.is_file()
        else b""
    )
    if (
        real_registry_before
        != real_registry_after
    ):
        raise RuntimeError(
            "XP+-04 bundle backfill "
            "mutated real XP registry"
        )

    return {
        "xp03": {
            "Legacy": legacy_doctor.status,
            "Next": next_doctor.status,
        },
        "xp035": {
            "Legacy": "cwd/session-only",
            "Next": "cwd/session-only",
            "registry_unchanged": True,
        },
        "xp04": {
            "Legacy_ratio": ratios["Legacy"],
            "Next_ratio": ratios["Next"],
            "threshold": 0.35,
            "zone2": bundle_zone2,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--legacy",
        required=True,
    )
    parser.add_argument(
        "--next",
        required=True,
    )
    parser.add_argument(
        "--xp-home",
        required=True,
    )
    args = parser.parse_args()

    legacy = (
        Path(args.legacy)
        .expanduser()
        .resolve()
    )
    next_repo = (
        Path(args.next)
        .expanduser()
        .resolve()
    )
    real_home = (
        Path(args.xp_home)
        .expanduser()
        .resolve()
    )

    install_original_repo_guard(
        legacy,
        next_repo,
    )

    print(
        "ZONE1: hashing original Legacy full tree...",
        flush=True,
    )
    legacy_before = full_tree_byte_snapshot(
        legacy
    )
    print(
        "ZONE1: hashing original Next full tree...",
        flush=True,
    )
    next_before = full_tree_byte_snapshot(
        next_repo
    )

    with tempfile.TemporaryDirectory(
        prefix="xp07-a-plus-"
    ) as td:
        root = Path(td)

        print(
            "ZONE2: physically copying Legacy...",
            flush=True,
        )
        legacy_copy = (
            prepare_acceptance_copy(
                legacy,
                root / "legacy",
            )
        )
        print(
            "ZONE2: physically copying Next...",
            flush=True,
        )
        next_copy = (
            prepare_acceptance_copy(
                next_repo,
                root / "next",
            )
        )

        replace_source_remote(
            legacy_copy,
            root / "legacy-remote-root",
        )
        replace_source_remote(
            next_copy,
            root / "next-remote-root",
        )

        backfill_evidence = backfill(
            real_home,
            legacy_copy,
            next_copy,
            root,
        )
        legacy_evidence = smoke_legacy(
            legacy_copy,
            real_home,
            root,
        )
        next_evidence = smoke_next(
            next_copy,
            real_home,
            root,
        )

    print(
        "ZONE1: re-hashing original Legacy...",
        flush=True,
    )
    legacy_after = full_tree_byte_snapshot(
        legacy
    )
    print(
        "ZONE1: re-hashing original Next...",
        flush=True,
    )
    next_after = full_tree_byte_snapshot(
        next_repo
    )

    zone1 = {
        "Legacy": assert_zone1_unchanged(
            legacy_before,
            legacy_after,
            "Legacy original",
        ),
        "Next": assert_zone1_unchanged(
            next_before,
            next_after,
            "Next original",
        ),
    }

    result = {
        "zone1": zone1,
        "legacy": legacy_evidence,
        "next": next_evidence,
        "backfill": backfill_evidence,
        "no_production_call_proof": {
            "zone1_originals_plain_read_copy_only": True,
            "source_remotes_replaced_with_local_temp_remotes": True,
            "control_remotes_local_temp_only": True,
            "database_credentials_removed": True,
            "postgres_apply_and_sql_test_methods_guarded": True,
            "deployment_policy_required_disabled": True,
            "no_harness_added_git_exclusions": True,
        },
    }
    print(
        json.dumps(
            result,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
