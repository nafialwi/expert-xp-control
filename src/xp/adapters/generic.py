from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .base import AdapterError, AdapterReadiness, CapabilityAdapter
from ..redaction import redact_text


ALLOWED_PURPOSES = frozenset(
    {"verify", "test", "build", "lint", "format-check"}
)

_DIRECT_NETWORK_OR_DEPLOY = frozenset(
    {
        "curl", "wget", "ssh", "scp", "sftp", "ftp", "nc", "ncat",
        "telnet", "rsync", "gh", "kubectl", "helm", "terraform",
        "ansible", "ansible-playbook", "vercel", "netlify", "wrangler",
        "firebase", "supabase",
    }
)

_SENSITIVE_ENV_MARKERS = (
    "TOKEN", "PASSWORD", "PASSWD", "SECRET", "API_KEY", "APIKEY",
    "AUTHORIZATION", "DATABASE_URL", "PRIVATE_KEY", "ACCESS_KEY",
)


@dataclass(frozen=True)
class GenericCommandSpec:
    command_id: str
    purpose: str
    argv: tuple[str, ...]
    cwd: str = "."
    timeout: int = 900
    paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class GenericCommandResult:
    command_id: str
    purpose: str
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


class GenericToolchainAdapter(CapabilityAdapter):
    """Allow-listed project command runner with no shell expansion."""

    def __init__(self, repo: Path, declarations: Mapping[str, Any] | None):
        self.repo = Path(repo).expanduser().resolve()
        if not self.repo.is_dir():
            raise AdapterError(f"repository does not exist: {self.repo}")
        self._specs = self._parse_declarations(declarations or {})

    def capabilities(self) -> set[str]:
        return {"generic-toolchain", "allowlisted-command"}

    @staticmethod
    def _inside(repo: Path, candidate: Path) -> bool:
        candidate = candidate.resolve()
        return candidate == repo or repo in candidate.parents

    @classmethod
    def _safe_repo_path(cls, repo: Path, base: Path, value: str) -> Path:
        raw = str(value).strip()
        if not raw:
            raise AdapterError("declared path must not be empty")
        if "://" in raw:
            raise AdapterError("URL/network targets are not allowed in generic commands")
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = base / candidate
        resolved = candidate.resolve()
        if not cls._inside(repo, resolved):
            raise AdapterError(f"path outside repository: {value}")
        return resolved

    @classmethod
    def _validate_argv_paths(
        cls,
        repo: Path,
        cwd: Path,
        argv: tuple[str, ...],
    ) -> None:
        for token in argv:
            value = token
            if "=" in token and token.startswith("-"):
                _, value = token.split("=", 1)
            if "://" in value:
                raise AdapterError("URL/network arguments are not allowed")
            if value.startswith("/") or value.startswith("./") or value.startswith("../"):
                cls._safe_repo_path(repo, cwd, value)

    @staticmethod
    def _blocked_direct_action(argv: tuple[str, ...]) -> str | None:
        executable = Path(argv[0]).name.lower()
        if executable in _DIRECT_NETWORK_OR_DEPLOY:
            return executable

        if executable == "git" and len(argv) > 1:
            action = argv[1].lower()
            if action in {"clone", "fetch", "pull", "push", "remote"}:
                return f"git {action}"

        if executable in {"npm", "pnpm", "yarn"} and len(argv) > 1:
            action = argv[1].lower()
            if action in {"install", "add", "publish", "login", "logout"}:
                return f"{executable} {action}"

        if executable in {"pip", "pip3"} and len(argv) > 1:
            if argv[1].lower() in {"install", "download"}:
                return f"{executable} {argv[1].lower()}"

        if executable == "cargo" and len(argv) > 1:
            if argv[1].lower() in {"publish", "install"}:
                return f"cargo {argv[1].lower()}"

        return None

    def _parse_declarations(
        self,
        declarations: Mapping[str, Any],
    ) -> dict[str, GenericCommandSpec]:
        if not isinstance(declarations, Mapping):
            raise AdapterError("toolchain_commands must be an object keyed by command id")

        specs: dict[str, GenericCommandSpec] = {}
        for command_id, raw in declarations.items():
            cid = str(command_id).strip()
            if not cid:
                raise AdapterError("toolchain command id must not be empty")
            if not isinstance(raw, Mapping):
                raise AdapterError(f"toolchain command {cid} must be an object")

            purpose = str(raw.get("purpose") or "").strip()
            if purpose not in ALLOWED_PURPOSES:
                raise AdapterError(
                    f"toolchain command {cid} has unsupported purpose: {purpose or '-'}"
                )

            argv_raw = raw.get("argv")
            if (
                not isinstance(argv_raw, list)
                or not argv_raw
                or not all(isinstance(value, str) and value for value in argv_raw)
            ):
                raise AdapterError(
                    f"toolchain command {cid} argv must be a non-empty string list"
                )
            argv = tuple(argv_raw)

            blocked = self._blocked_direct_action(argv)
            if blocked:
                raise AdapterError(
                    f"toolchain command {cid} uses blocked network/deploy action: {blocked}"
                )

            timeout = raw.get("timeout", 900)
            if (
                not isinstance(timeout, int)
                or isinstance(timeout, bool)
                or not 1 <= timeout <= 3600
            ):
                raise AdapterError(
                    f"toolchain command {cid} timeout must be integer 1..3600"
                )

            cwd_value = str(raw.get("cwd") or ".")
            cwd = self._safe_repo_path(self.repo, self.repo, cwd_value)

            paths_raw = raw.get("paths", [])
            if (
                not isinstance(paths_raw, list)
                or not all(isinstance(value, str) and value for value in paths_raw)
            ):
                raise AdapterError(
                    f"toolchain command {cid} paths must be a string list"
                )
            for value in paths_raw:
                self._safe_repo_path(self.repo, cwd, value)

            self._validate_argv_paths(self.repo, cwd, argv)

            executable = argv[0]
            if "/" in executable:
                executable_path = self._safe_repo_path(
                    self.repo, cwd, executable
                )
                if not executable_path.is_file():
                    raise AdapterError(
                        f"toolchain command {cid} executable not found: {executable}"
                    )

            specs[cid] = GenericCommandSpec(
                command_id=cid,
                purpose=purpose,
                argv=argv,
                cwd=cwd_value,
                timeout=timeout,
                paths=tuple(paths_raw),
            )

        return specs

    def readiness(self) -> AdapterReadiness:
        missing: list[str] = []
        for spec in self._specs.values():
            executable = spec.argv[0]
            if "/" in executable:
                cwd = self._safe_repo_path(self.repo, self.repo, spec.cwd)
                path = self._safe_repo_path(self.repo, cwd, executable)
                if not path.is_file():
                    missing.append(f"{spec.command_id}:{executable}")
            elif shutil.which(executable) is None:
                missing.append(f"{spec.command_id}:{executable}")

        if not self._specs:
            return AdapterReadiness(
                False,
                "NOT_READY",
                "No generic toolchain commands are declared.",
                tuple(sorted(self.capabilities())),
                {"declared_commands": 0},
            )
        if missing:
            return AdapterReadiness(
                False,
                "NOT_READY",
                "Missing executable(s): " + ", ".join(missing),
                tuple(sorted(self.capabilities())),
                {"declared_commands": len(self._specs)},
            )
        return AdapterReadiness(
            True,
            "READY",
            "All declared generic toolchain commands are locally resolvable.",
            tuple(sorted(self.capabilities())),
            {
                "declared_commands": len(self._specs),
                "purposes": sorted(
                    {spec.purpose for spec in self._specs.values()}
                ),
            },
        )

    @staticmethod
    def _child_environment() -> dict[str, str]:
        env: dict[str, str] = {}
        for key, value in os.environ.items():
            upper = key.upper()
            if any(marker in upper for marker in _SENSITIVE_ENV_MARKERS):
                continue
            env[key] = value
        env["XP_GENERIC_TOOLCHAIN"] = "1"
        return env

    def resolve(self, command_id: str) -> GenericCommandSpec:
        cid = str(command_id).strip()
        try:
            return self._specs[cid]
        except KeyError as exc:
            raise AdapterError(
                f"generic toolchain command not declared: {cid}"
            ) from exc

    def run(self, command_id: str) -> GenericCommandResult:
        spec = self.resolve(command_id)
        cwd = self._safe_repo_path(self.repo, self.repo, spec.cwd)

        try:
            result = subprocess.run(
                list(spec.argv),
                cwd=cwd,
                env=self._child_environment(),
                text=True,
                capture_output=True,
                timeout=spec.timeout,
                shell=False,
            )
            return GenericCommandResult(
                spec.command_id,
                spec.purpose,
                result.returncode,
                redact_text(result.stdout),
                redact_text(result.stderr),
                False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = (
                exc.stdout.decode()
                if isinstance(exc.stdout, bytes)
                else (exc.stdout or "")
            )
            stderr = (
                exc.stderr.decode()
                if isinstance(exc.stderr, bytes)
                else (exc.stderr or "")
            )
            return GenericCommandResult(
                spec.command_id,
                spec.purpose,
                124,
                redact_text(stdout),
                redact_text(
                    stderr + f"\ncommand timeout after {spec.timeout}s"
                ),
                True,
            )
        except OSError as exc:
            return GenericCommandResult(
                spec.command_id,
                spec.purpose,
                127,
                "",
                redact_text(str(exc)),
                False,
            )
