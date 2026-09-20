from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
from typing import Callable


class CapabilityState(str, Enum):
    READY = "READY"
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


@dataclass(frozen=True)
class CapabilityObservation:
    capability_id: str
    state: CapabilityState
    executable: str | None
    version: str | None
    evidence: str | None = None
    source: str = "local"
    network_used: bool = False

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["state"] = self.state.value
        return data


def _default_version_probe(name: str, executable: str) -> str:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(
        [executable, "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=3,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{name} version probe failed with {result.returncode}")
    text = (result.stdout or result.stderr).strip()
    if not text:
        raise RuntimeError(f"{name} version probe returned no output")
    return text.splitlines()[0][:200]


def _first_existing(candidates: list[Path]) -> str | None:
    for path in candidates:
        expanded = path.expanduser()
        if expanded.exists():
            return str(expanded)
    return None


def _default_presence(name: str) -> str | None:
    if name == "hermes":
        executable = shutil.which("hermes") or shutil.which("hermes-agent")
        if executable:
            return executable
        return _first_existing(
            [
                Path("~/.hermes/hermes-agent"),
            ]
        )

    if name == "local_qwen":
        hf_home = Path(
            os.environ.get("HF_HOME", "~/.cache/huggingface")
        ).expanduser()
        hub = hf_home / "hub"
        if hub.is_dir():
            matches = sorted(hub.glob("models--Qwen--*Instruct-GGUF"))
            if matches:
                return str(matches[0])

        llama = shutil.which("llama-server")
        if llama:
            return llama

        return _first_existing(
            [
                Path("~/llama.cpp/build/bin/llama-server"),
                Path("~/llama.cpp/llama-server"),
            ]
        )

    return None


class LocalCapabilityRegistry:
    """Observe bounded local capabilities without network probes or AI execution."""

    _FOUNDATION = ("python", "git", "node")
    _PRESENCE_ONLY = ("local_qwen", "hermes")

    def __init__(
        self,
        *,
        which: Callable[[str], str | None] = shutil.which,
        version_probe: Callable[[str, str], str] = _default_version_probe,
        presence: Callable[[str], str | None] = _default_presence,
        sqlite_version: str = sqlite3.sqlite_version,
    ):
        self._which = which
        self._version_probe = version_probe
        self._presence = presence
        self._sqlite_version = sqlite_version

    def snapshot(self) -> dict[str, dict[str, object]]:
        observations: dict[str, dict[str, object]] = {}

        for capability_id in self._FOUNDATION:
            executable = self._which(capability_id)
            if executable is None:
                observation = CapabilityObservation(
                    capability_id=capability_id,
                    state=CapabilityState.UNAVAILABLE,
                    executable=None,
                    version=None,
                )
            else:
                try:
                    version = self._version_probe(capability_id, executable)
                except Exception:
                    observation = CapabilityObservation(
                        capability_id=capability_id,
                        state=CapabilityState.NEEDS_ATTENTION,
                        executable=executable,
                        version=None,
                        evidence=executable,
                    )
                else:
                    observation = CapabilityObservation(
                        capability_id=capability_id,
                        state=CapabilityState.READY,
                        executable=executable,
                        version=version,
                        evidence=executable,
                    )
            observations[capability_id] = observation.as_dict()

        observations["sqlite"] = CapabilityObservation(
            capability_id="sqlite",
            state=CapabilityState.READY,
            executable=None,
            version=self._sqlite_version,
            evidence="python-stdlib-sqlite3",
        ).as_dict()

        for capability_id in self._PRESENCE_ONLY:
            evidence = self._presence(capability_id)
            observations[capability_id] = CapabilityObservation(
                capability_id=capability_id,
                state=(
                    CapabilityState.AVAILABLE
                    if evidence is not None
                    else CapabilityState.UNAVAILABLE
                ),
                executable=None,
                version=None,
                evidence=evidence,
            ).as_dict()

        return observations
