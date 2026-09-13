from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .base import AdapterError, AdapterReadiness, CapabilityAdapter




@dataclass(frozen=True)
class GitSafepointResult:
    head: str
    committed: bool
    pushed: bool
    branch: str | None


@dataclass(frozen=True)
class GitState:
    branch: str | None
    head: str
    dirty: bool
    ahead: int = 0
    behind: int = 0
    diverged: bool = False
    remote: str | None = None
    upstream: str | None = None
    fetch_checked: bool = False
    fetch_ok: bool | None = None
    fetch_error: str | None = None


class GitAdapter(CapabilityAdapter):
    def __init__(self, repo: Path):
        self.repo = Path(repo)

    def capabilities(self) -> set[str]:
        return {"git-state", "git-fingerprint", "git-fetch", "git-push"}

    def readiness(self) -> AdapterReadiness:
        import shutil
        if shutil.which("git") is None:
            return AdapterReadiness(
                False, "NOT_READY", "git executable not found",
                tuple(sorted(self.capabilities())),
            )
        if not (self.repo / ".git").exists():
            return AdapterReadiness(
                False, "NOT_READY", "repository has no .git metadata",
                tuple(sorted(self.capabilities())),
            )
        try:
            state = self.state(fetch=False)
        except Exception as exc:
            return AdapterReadiness(
                False, "NOT_READY", f"git state unavailable: {exc}",
                tuple(sorted(self.capabilities())),
            )
        return AdapterReadiness(
            True,
            "READY",
            "Git repository is readable without network access.",
            tuple(sorted(self.capabilities())),
            {
                "branch": state.branch,
                "dirty": state.dirty,
                "remote_configured": bool(state.remote),
            },
        )

    def _run(self, *args: str, check: bool = True) -> str:
        result = subprocess.run(
            ["git", *args], cwd=self.repo, text=True, capture_output=True
        )
        if check and result.returncode != 0:
            raise AdapterError(result.stderr.strip() or "git command failed")
        return result.stdout.strip()

    def state(self, fetch: bool = True) -> GitState:
        fetch_checked = bool(fetch)
        fetch_ok = None
        fetch_error = None
        if fetch:
            result = subprocess.run(["git", "fetch", "--quiet"], cwd=self.repo, text=True, capture_output=True)
            fetch_ok = result.returncode == 0
            if not fetch_ok:
                fetch_error = (result.stderr.strip() or result.stdout.strip() or "git fetch failed")
        branch = self._run("branch", "--show-current") or None
        head = self._run("rev-parse", "HEAD")
        dirty = bool(self._run("status", "--porcelain"))
        remote = self._run("remote", "get-url", "origin", check=False) or None
        ahead = behind = 0
        upstream = None
        if branch:
            upstream = self._run("rev-parse", "--abbrev-ref", "@{upstream}", check=False) or None
            if upstream:
                counts = self._run("rev-list", "--left-right", "--count", f"{upstream}...HEAD")
                if counts:
                    behind_s, ahead_s = counts.split()
                    behind, ahead = int(behind_s), int(ahead_s)
        return GitState(
            branch=branch,
            head=head,
            dirty=dirty,
            ahead=ahead,
            behind=behind,
            diverged=bool(ahead and behind),
            remote=remote,
            upstream=upstream,
            fetch_checked=fetch_checked,
            fetch_ok=fetch_ok,
            fetch_error=fetch_error,
        )

    def source_fingerprint(self) -> str:
        state = self.state(fetch=False)
        marker = f"git:{state.head}"
        return hashlib.sha256(marker.encode("utf-8")).hexdigest()

    def working_fingerprint(self) -> str:
        state = self.state(fetch=False)
        diff = self._run("diff", "--binary", "HEAD", "--", check=False)
        untracked = self._run("ls-files", "--others", "--exclude-standard", check=False)
        pieces = [f"head={state.head}", diff]
        for rel in sorted(filter(None, untracked.splitlines())):
            path = self.repo / rel
            if path.is_file():
                pieces.append(f"untracked:{rel}:{hashlib.sha256(path.read_bytes()).hexdigest()}")
            else:
                pieces.append(f"untracked:{rel}:nonfile")
        return hashlib.sha256("\n".join(pieces).encode("utf-8")).hexdigest()

    def push_current_branch(self, *, remote: str = "origin") -> GitSafepointResult:
        state = self.state(fetch=False)
        if not state.branch:
            raise AdapterError("Cannot push from detached HEAD")
        head = self._run("rev-parse", "HEAD")
        result = subprocess.run(
            ["git", "push", "-u", remote, state.branch],
            cwd=self.repo,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            raise AdapterError(result.stderr.strip() or result.stdout.strip() or "git push failed")
        return GitSafepointResult(head=head, committed=False, pushed=True, branch=state.branch)

    def create_safepoint(self, message: str, *, push: bool = True, remote: str = "origin") -> GitSafepointResult:
        state = self.state(fetch=False)
        if not state.branch:
            raise AdapterError("Cannot create safepoint from detached HEAD")
        committed = False
        if state.dirty:
            self._run("add", "-A")
            result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=self.repo,
                text=True,
                capture_output=True,
            )
            if result.returncode != 0:
                raise AdapterError(result.stderr.strip() or result.stdout.strip() or "git commit failed")
            committed = True
        head = self._run("rev-parse", "HEAD")
        pushed = False
        if push:
            result = subprocess.run(
                ["git", "push", "-u", remote, state.branch],
                cwd=self.repo,
                text=True,
                capture_output=True,
            )
            if result.returncode != 0:
                raise AdapterError(result.stderr.strip() or result.stdout.strip() or "git push failed")
            pushed = True
        return GitSafepointResult(head=head, committed=committed, pushed=pushed, branch=state.branch)
