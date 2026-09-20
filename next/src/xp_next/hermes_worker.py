from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Callable
from urllib.parse import urlparse
from urllib.request import urlopen

from .isolated_workspace import workspace_changed_paths
from .worker_contract import (
    WorkerReadiness,
    WorkerRequest,
    WorkerResult,
    WorkerStatus,
)


class HermesWorkerConfigError(ValueError):
    pass


Runner = Callable[..., object]
HealthProbe = Callable[[str, float], dict[str, object]]
ContextProbe = Callable[[str, float], int]
BinaryExists = Callable[[str], bool]
MutationProbe = Callable[[Path], tuple[str, ...]]


def _default_binary_exists(path: str) -> bool:
    return Path(path).is_file() and os.access(path, os.X_OK)


def _default_health_probe(url: str, timeout: float) -> dict[str, object]:
    with urlopen(url, timeout=timeout) as response:
        data = json.loads(response.read(64_000).decode("utf-8", "replace"))
    if not isinstance(data, dict):
        raise RuntimeError("local model health response is not an object")
    return data


def _default_context_probe(url: str, timeout: float) -> int:
    with urlopen(url, timeout=timeout) as response:
        data = json.loads(response.read(256_000).decode("utf-8", "replace"))
    if not isinstance(data, dict):
        raise RuntimeError("local model props response is not an object")
    settings = data.get("default_generation_settings")
    if not isinstance(settings, dict):
        raise RuntimeError("local model props missing default_generation_settings")
    value = settings.get("n_ctx")
    if not isinstance(value, int) or value <= 0:
        raise RuntimeError("local model props missing valid n_ctx")
    return value


def _validate_loopback_v1(base_url: str) -> tuple[str, str, str]:
    parsed = urlparse(base_url)
    if parsed.scheme != "http":
        raise HermesWorkerConfigError("Hermes local model endpoint must use http")
    if parsed.hostname not in {"127.0.0.1", "::1"}:
        raise HermesWorkerConfigError("Hermes local model endpoint must be loopback")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HermesWorkerConfigError("Hermes model URL must not include credentials/query/fragment")
    if parsed.path.rstrip("/") != "/v1":
        raise HermesWorkerConfigError("Hermes model URL must end in /v1")
    host = parsed.hostname
    authority = f"[{host}]" if ":" in host else host
    if parsed.port is not None:
        authority = f"{authority}:{parsed.port}"
    origin = f"http://{authority}"
    return base_url.rstrip("/"), f"{origin}/health", f"{origin}/props"


class HermesLocalWorker:
    """Hermes worker bound to a loopback local model and isolated workspace."""

    def __init__(
        self,
        *,
        binary: str | None = None,
        base_url: str = "http://127.0.0.1:18085/v1",
        model: str = "local",
        context_length: int = 65536,
        timeout: float = 480.0,
        binary_exists: BinaryExists = _default_binary_exists,
        health_probe: HealthProbe = _default_health_probe,
        context_probe: ContextProbe = _default_context_probe,
        mutation_probe: MutationProbe = workspace_changed_paths,
        runner: Runner = subprocess.run,
    ):
        resolved_binary = binary or shutil.which("hermes")
        if not resolved_binary:
            resolved_binary = "hermes"
        if not model.strip():
            raise HermesWorkerConfigError("model must not be empty")
        if context_length < 64000:
            raise HermesWorkerConfigError("Hermes requires at least 64000 context tokens")
        if timeout <= 0:
            raise HermesWorkerConfigError("timeout must be positive")
        self.binary = resolved_binary
        self.base_url, self.health_url, self.props_url = _validate_loopback_v1(base_url)
        self.model = model.strip()
        self.context_length = context_length
        self.timeout = timeout
        self._binary_exists = binary_exists
        self._health_probe = health_probe
        self._context_probe = context_probe
        self._mutation_probe = mutation_probe
        self._runner = runner

    def readiness(self) -> WorkerReadiness:
        if not self._binary_exists(self.binary):
            return WorkerReadiness(
                ready=False,
                status="NEEDS_ATTENTION",
                detail="Hermes executable is unavailable",
                backend_id="hermes",
                model_transport="loopback_http",
                containment="isolated_copy_sanitized_env_best_effort_network_block",
            )
        try:
            health = self._health_probe(self.health_url, min(self.timeout, 5.0))
        except Exception as exc:
            return WorkerReadiness(
                ready=False,
                status="NEEDS_ATTENTION",
                detail=f"{type(exc).__name__}: {exc}"[:500],
                backend_id="hermes",
                model_transport="loopback_http",
                containment="isolated_copy_sanitized_env_best_effort_network_block",
            )
        health_ready = str(health.get("status", "")).lower() == "ok"
        if not health_ready:
            return WorkerReadiness(
                ready=False,
                status="NEEDS_ATTENTION",
                detail=f"unexpected local model health: {health.get('status')!r}",
                backend_id="hermes",
                model_transport="loopback_http",
                containment="isolated_copy_sanitized_env_best_effort_network_block",
            )

        try:
            effective_context = self._context_probe(
                self.props_url,
                min(self.timeout, 5.0),
            )
        except Exception as exc:
            return WorkerReadiness(
                ready=False,
                status="NEEDS_ATTENTION",
                detail=f"context probe failed: {type(exc).__name__}: {exc}"[:500],
                backend_id="hermes",
                model_transport="loopback_http",
                containment="isolated_copy_sanitized_env_best_effort_network_block",
            )

        required_context = max(64000, self.context_length)
        if effective_context < required_context:
            return WorkerReadiness(
                ready=False,
                status="NEEDS_ATTENTION",
                detail=(
                    f"effective local model context {effective_context} is below "
                    f"required {required_context}"
                ),
                backend_id="hermes",
                model_transport="loopback_http",
                containment="isolated_copy_sanitized_env_best_effort_network_block",
            )

        return WorkerReadiness(
            ready=True,
            status="READY",
            detail=(
                "Hermes executable and loopback model are available; "
                f"effective_context={effective_context}"
            ),
            backend_id="hermes",
            model_transport="loopback_http",
            containment="isolated_copy_sanitized_env_best_effort_network_block",
        )

    def build_environment(self, *, home: Path, tmp: Path) -> dict[str, str]:
        home = home.expanduser().resolve()
        temp = tmp.expanduser().resolve()
        hermes_home = home / ".hermes"
        hermes_home.mkdir(parents=True, exist_ok=True, mode=0o700)
        env = {
            "HOME": str(home),
            "HERMES_HOME": str(hermes_home),
            "PATH": os.environ.get("PATH", ""),
            "PREFIX": os.environ.get("PREFIX", ""),
            "TMPDIR": str(temp),
            "TERM": os.environ.get("TERM", "xterm-256color"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "OPENAI_BASE_URL": self.base_url,
            "OPENAI_API_KEY": "local-fixture-key",
            "NO_PROXY": "127.0.0.1,localhost,::1",
            "no_proxy": "127.0.0.1,localhost,::1",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "http://127.0.0.1:9",
            "http_proxy": "http://127.0.0.1:9",
            "https_proxy": "http://127.0.0.1:9",
            "all_proxy": "http://127.0.0.1:9",
            "HERMES_ACP_SKIP_CONFIGURED_MCP": "1",
        }
        return env

    def _write_config(self, home: Path) -> None:
        hermes_home = home.expanduser().resolve() / ".hermes"
        hermes_home.mkdir(parents=True, exist_ok=True, mode=0o700)
        config = (
            "model:\n"
            "  provider: custom\n"
            f"  default: {self.model}\n"
            f"  base_url: {self.base_url}\n"
            "  api_key: local-fixture-key\n"
            "  api_mode: chat_completions\n"
            f"  context_length: {self.context_length}\n"
            "mcp_servers: {}\n"
            "tools:\n"
            "  tool_search:\n"
            "    enabled: off\n"
            "  connectors:\n"
            "    enabled: false\n"
            "memory:\n"
            "  memory_enabled: false\n"
            "  user_profile_enabled: false\n"
            "agent:\n"
            "  max_turns: 2\n"
        )
        (hermes_home / "config.yaml").write_text(config, encoding="utf-8")

    def run(
        self,
        request: WorkerRequest,
        *,
        home: Path,
        tmp: Path,
    ) -> WorkerResult:
        readiness = self.readiness()
        if not readiness.ready:
            return WorkerResult(
                status=WorkerStatus.NEEDS_ATTENTION,
                output="",
                returncode=2,
                backend_id="hermes",
                model_transport="loopback_http",
                containment=readiness.containment,
                detail=readiness.detail,
            )

        home = home.expanduser().resolve()
        temp = tmp.expanduser().resolve()
        self._write_config(home)
        env = self.build_environment(home=home, tmp=temp)
        governed_prompt = (
            "XP NEXT ISOLATED WORKSPACE RULES:\n"
            f"- Work only inside: {request.cwd}\n"
            "- You may modify files only inside that directory.\n"
            "- Do not access or modify any original project outside this workspace.\n"
            "- Do not use network tools or external services.\n"
            "- Do not push, deploy, publish, install packages, or change databases.\n"
            "- Make the smallest change required by the user task and run only local verification.\n\n"
            "USER TASK:\n"
            f"{request.prompt}"
        )
        cmd = [
            self.binary,
            "-z",
            governed_prompt,
            "--provider",
            "custom",
            "--model",
            self.model,
            "--in",
            str(request.cwd),
            "--ignore-rules",
            "-t",
            "file",
        ]
        try:
            proc = self._runner(
                cmd,
                cwd=request.cwd,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return WorkerResult(
                status=WorkerStatus.NEEDS_ATTENTION,
                output="",
                returncode=124,
                backend_id="hermes",
                model_transport="loopback_http",
                containment=readiness.containment,
                detail="Hermes isolated worker timed out",
            )
        except Exception as exc:
            return WorkerResult(
                status=WorkerStatus.NEEDS_ATTENTION,
                output="",
                returncode=1,
                backend_id="hermes",
                model_transport="loopback_http",
                containment=readiness.containment,
                detail=f"{type(exc).__name__}: {exc}"[:500],
            )

        stdout = str(getattr(proc, "stdout", "") or "").strip()
        stderr = str(getattr(proc, "stderr", "") or "").strip()
        returncode = int(getattr(proc, "returncode", 1))
        output = stdout if not stderr else (stdout + "\n" + stderr).strip()

        if returncode != 0:
            return WorkerResult(
                status=WorkerStatus.NEEDS_ATTENTION,
                output=output[:20000],
                returncode=returncode,
                backend_id="hermes",
                model_transport="loopback_http",
                containment=readiness.containment,
                apply_to_original_performed=False,
                detail=f"Hermes exited with {returncode}",
            )

        try:
            changed_paths = self._mutation_probe(request.cwd)
        except Exception as exc:
            return WorkerResult(
                status=WorkerStatus.NEEDS_ATTENTION,
                output=output[:20000],
                returncode=returncode,
                backend_id="hermes",
                model_transport="loopback_http",
                containment=readiness.containment,
                apply_to_original_performed=False,
                detail=f"sandbox mutation audit failed: {type(exc).__name__}: {exc}"[:500],
            )

        if not changed_paths:
            return WorkerResult(
                status=WorkerStatus.NEEDS_ATTENTION,
                output=output[:20000],
                returncode=returncode,
                backend_id="hermes",
                model_transport="loopback_http",
                containment=readiness.containment,
                apply_to_original_performed=False,
                detail="Hermes returned successfully but no sandbox mutation was observed",
            )

        return WorkerResult(
            status=WorkerStatus.COMPLETED,
            output=output[:20000],
            returncode=returncode,
            backend_id="hermes",
            model_transport="loopback_http",
            containment=readiness.containment,
            apply_to_original_performed=False,
            detail=f"sandbox mutation observed: {', '.join(changed_paths[:20])}",
        )
