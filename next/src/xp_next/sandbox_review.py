from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

from .isolated_workspace import workspace_changed_paths


_FORBIDDEN_VERIFIER_EXECUTABLES = {
    "sh",
    "bash",
    "zsh",
    "fish",
    "curl",
    "wget",
    "ssh",
    "scp",
    "rsync",
}


class ReviewStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True)
class VerifierSpec:
    name: str
    argv: tuple[str, ...]
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("verifier name must not be empty")
        if not self.argv or not self.argv[0].strip():
            raise ValueError("verifier argv must not be empty")
        executable = Path(self.argv[0]).name
        if executable in _FORBIDDEN_VERIFIER_EXECUTABLES:
            raise ValueError(f"verifier executable is forbidden in CP-06A: {executable}")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 300:
            raise ValueError("verifier timeout must be > 0 and <= 300 seconds")


@dataclass(frozen=True)
class VerifierResult:
    name: str
    status: ReviewStatus
    returncode: int | None
    output: str
    detail: str

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True)
class ReviewBundle:
    status: ReviewStatus
    summary: str
    changed_files: tuple[str, ...]
    bounded_diff: str
    diff_truncated: bool
    verifiers: tuple[VerifierResult, ...]
    apply_to_original_performed: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "summary": self.summary,
            "changed_files": list(self.changed_files),
            "bounded_diff": self.bounded_diff,
            "diff_truncated": self.diff_truncated,
            "verifiers": [item.as_dict() for item in self.verifiers],
            "apply_to_original_performed": self.apply_to_original_performed,
        }

    def render_text(self) -> str:
        changed = "\n".join(f"- {path}" for path in self.changed_files) or "- none"
        verifier_lines = []
        if self.verifiers:
            for item in self.verifiers:
                suffix = f" (rc={item.returncode})" if item.returncode is not None else ""
                verifier_lines.append(
                    f"- {item.name}: {item.status.value}{suffix} — {item.detail}"
                )
        else:
            verifier_lines.append("- none configured")
        verifier_text = "\n".join(verifier_lines)
        truncated = "yes" if self.diff_truncated else "no"
        return (
            "XP Next Sandbox Review\n"
            f"Status: {self.status.value}\n"
            f"Summary: {self.summary}\n"
            "Apply to original performed: no\n"
            f"Diff truncated: {truncated}\n\n"
            "Changed files:\n"
            f"{changed}\n\n"
            "Verifier results:\n"
            f"{verifier_text}\n\n"
            "Bounded diff:\n"
            f"{self.bounded_diff}"
        )


def _git(project: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        ["git", "-C", str(project), *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )


def _content_digest(project: Path) -> str:
    digest = hashlib.sha256()
    separator = bytes([0])
    for path in sorted(project.rglob("*")):
        rel = path.relative_to(project)
        if ".git" in rel.parts or not path.is_file():
            continue
        digest.update(rel.as_posix().encode("utf-8"))
        digest.update(separator)
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        digest.update(separator)
    return digest.hexdigest()


def _path_diff(project: Path, relative: str) -> str:
    tracked = _git(
        project,
        "ls-files",
        "--error-unmatch",
        "--",
        relative,
        check=False,
    )
    if tracked.returncode == 0:
        result = _git(
            project,
            "diff",
            "--no-ext-diff",
            "--unified=3",
            "HEAD",
            "--",
            relative,
            check=False,
        )
        return result.stdout

    result = _git(
        project,
        "diff",
        "--no-index",
        "--no-ext-diff",
        "--unified=3",
        "--",
        "/dev/null",
        relative,
        check=False,
    )
    if result.returncode not in {0, 1}:
        return f"[unable to render diff for {relative}: rc={result.returncode}]\n"
    return result.stdout


def _bounded_diff(
    project: Path,
    changed_files: tuple[str, ...],
    *,
    max_diff_chars: int,
) -> tuple[str, bool]:
    if max_diff_chars < 200:
        raise ValueError("max_diff_chars must be at least 200")
    combined = "".join(_path_diff(project, path) for path in changed_files)
    if len(combined) <= max_diff_chars:
        return combined, False
    marker = "\n[DIFF TRUNCATED]\n"
    return combined[:max_diff_chars] + marker, True


def _verifier_environment(home: Path, tmp: Path) -> dict[str, str]:
    return {
        "HOME": str(home),
        "TMPDIR": str(tmp),
        "PATH": os.environ.get("PATH", ""),
        "PREFIX": os.environ.get("PREFIX", ""),
        "TERM": os.environ.get("TERM", "xterm-256color"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "NO_PROXY": "",
        "no_proxy": "",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "ALL_PROXY": "http://127.0.0.1:9",
        "http_proxy": "http://127.0.0.1:9",
        "https_proxy": "http://127.0.0.1:9",
        "all_proxy": "http://127.0.0.1:9",
    }


def _run_verifier(project: Path, spec: VerifierSpec) -> VerifierResult:
    before_digest = _content_digest(project)
    before_paths = workspace_changed_paths(project)

    with tempfile.TemporaryDirectory(
        prefix="xpnext-verify-home-",
        dir=str(project.parent),
    ) as home_dir, tempfile.TemporaryDirectory(
        prefix="xpnext-verify-tmp-",
        dir=str(project.parent),
    ) as tmp_dir:
        try:
            result = subprocess.run(
                list(spec.argv),
                cwd=project,
                env=_verifier_environment(Path(home_dir), Path(tmp_dir)),
                capture_output=True,
                text=True,
                timeout=spec.timeout_seconds,
                check=False,
                shell=False,
            )
            returncode: int | None = result.returncode
            output = ((result.stdout or "") + (result.stderr or ""))[:8000]
            command_ok = result.returncode == 0
            detail = "command passed" if command_ok else f"command failed with rc={result.returncode}"
        except subprocess.TimeoutExpired as exc:
            returncode = None
            output = (
                ((exc.stdout or "") if isinstance(exc.stdout, str) else "")
                + ((exc.stderr or "") if isinstance(exc.stderr, str) else "")
            )[:8000]
            command_ok = False
            detail = f"verifier timed out after {spec.timeout_seconds:g}s"
        except Exception as exc:
            returncode = None
            output = ""
            command_ok = False
            detail = f"{type(exc).__name__}: {exc}"[:500]

    after_digest = _content_digest(project)
    after_paths = workspace_changed_paths(project)
    mutated = before_digest != after_digest or before_paths != after_paths
    if mutated:
        return VerifierResult(
            name=spec.name,
            status=ReviewStatus.FAIL,
            returncode=returncode,
            output=output,
            detail="verifier mutated sandbox; review failed closed",
        )
    return VerifierResult(
        name=spec.name,
        status=ReviewStatus.PASS if command_ok else ReviewStatus.FAIL,
        returncode=returncode,
        output=output,
        detail=detail,
    )


def build_review_bundle(
    project_root: Path | str,
    *,
    verifier_specs: tuple[VerifierSpec, ...] = (),
    max_diff_chars: int = 12_000,
) -> ReviewBundle:
    project = Path(project_root).expanduser().resolve(strict=True)
    if not project.is_dir():
        raise ValueError("project_root must be a directory")
    if not (project / ".git").exists():
        raise ValueError("sandbox project must be a Git repository")

    remotes = _git(project, "remote").stdout.split()
    changed = workspace_changed_paths(project)

    if remotes:
        diff, truncated = _bounded_diff(project, changed, max_diff_chars=max_diff_chars)
        return ReviewBundle(
            status=ReviewStatus.FAIL,
            summary="Sandbox has a Git remote; review failed closed.",
            changed_files=changed,
            bounded_diff=diff,
            diff_truncated=truncated,
            verifiers=(),
        )

    if not changed:
        return ReviewBundle(
            status=ReviewStatus.FAIL,
            summary="Sandbox has no changes to review.",
            changed_files=(),
            bounded_diff="",
            diff_truncated=False,
            verifiers=(),
        )

    diff_check = _git(project, "diff", "--check", "HEAD", "--", check=False)
    if diff_check.returncode != 0:
        diff, truncated = _bounded_diff(project, changed, max_diff_chars=max_diff_chars)
        return ReviewBundle(
            status=ReviewStatus.FAIL,
            summary="Git diff check failed.",
            changed_files=changed,
            bounded_diff=diff,
            diff_truncated=truncated,
            verifiers=(
                VerifierResult(
                    name="git-diff-check",
                    status=ReviewStatus.FAIL,
                    returncode=diff_check.returncode,
                    output=(diff_check.stdout + diff_check.stderr)[:8000],
                    detail="git diff --check failed",
                ),
            ),
        )

    verifier_results = tuple(_run_verifier(project, spec) for spec in verifier_specs)

    final_changed = workspace_changed_paths(project)
    diff, truncated = _bounded_diff(
        project,
        final_changed,
        max_diff_chars=max_diff_chars,
    )

    if any(item.status is ReviewStatus.FAIL for item in verifier_results):
        if any("mutated sandbox" in item.detail for item in verifier_results):
            summary = "A verifier mutated sandbox; review failed closed."
        else:
            summary = "One or more explicit verifiers failed."
        status = ReviewStatus.FAIL
    elif not verifier_results:
        summary = "No explicit verifier configured; structural review only."
        status = ReviewStatus.UNVERIFIED
    else:
        summary = "All configured verifiers passed; sandbox is ready for human review."
        status = ReviewStatus.PASS

    return ReviewBundle(
        status=status,
        summary=summary,
        changed_files=final_changed,
        bounded_diff=diff,
        diff_truncated=truncated,
        verifiers=verifier_results,
    )
