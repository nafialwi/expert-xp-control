from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import os
import shutil
import subprocess
from typing import Callable


class CapabilityState(str, Enum):
    READY = "READY"
    UNAVAILABLE = "UNAVAILABLE"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


@dataclass(frozen=True)
class CapabilityObservation:
    capability_id: str
    state: CapabilityState
    executable: str | None
    version: str | None
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


class LocalCapabilityRegistry:
    """Observe a bounded set of local tools without any network probe."""

    _FOUNDATION = ("python", "git", "node")

    def __init__(
        self,
        *,
        which: Callable[[str], str | None] = shutil.which,
        version_probe: Callable[[str, str], str] = _default_version_probe,
    ):
        self._which = which
        self._version_probe = version_probe

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
                    )
                else:
                    observation = CapabilityObservation(
                        capability_id=capability_id,
                        state=CapabilityState.READY,
                        executable=executable,
                        version=version,
                    )
            observations[capability_id] = observation.as_dict()
        return observations
