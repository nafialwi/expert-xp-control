#!/usr/bin/env python3
# XP_PLUS_CANONICAL_INSTALLER_V1
from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile
from pathlib import Path


_VERSION_RE = re.compile(
    r'(?m)^__version__\s*=\s*["\']([^"\']+)["\']\s*$'
)


def source_version(source: Path) -> str:
    init_file = source / "src" / "xp" / "__init__.py"
    if not init_file.is_file():
        raise FileNotFoundError(f"XP source version file missing: {init_file}")
    match = _VERSION_RE.search(init_file.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError("XP source version assignment not found")
    version = match.group(1).strip()
    if not version:
        raise RuntimeError("XP source version is empty")
    return version


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(value, encoding="utf-8")
    os.replace(temp, path)


def _copy_source(source: Path, destination: Path) -> None:
    def ignore(_directory: str, names: list[str]) -> list[str]:
        blocked = {".git", "__pycache__", ".pytest_cache"}
        return [
            name
            for name in names
            if name in blocked or name.endswith(".pyc")
        ]

    shutil.copytree(
        source,
        destination,
        symlinks=True,
        ignore=ignore,
    )


def _launcher_text() -> str:
    return """#!/usr/bin/env sh
ROOT="$HOME/.expert-workstation"
ACTIVE_FILE="$ROOT/active-version"
if [ ! -f "$ACTIVE_FILE" ]; then
    echo "XP active version is missing" >&2
    false
fi
VERSION="$(cat "$ACTIVE_FILE")"
ENGINE="$ROOT/versions/$VERSION"
if [ ! -d "$ENGINE/src/xp" ]; then
    echo "XP active engine is missing: $VERSION" >&2
    false
fi
export PYTHONPATH="$ENGINE/src${PYTHONPATH:+:$PYTHONPATH}"
exec python -m xp.cli "$@"
"""


def install_into(home: Path, source: Path | None = None) -> Path:
    home = Path(home).expanduser().resolve()
    source = (
        Path(source).expanduser().resolve()
        if source is not None
        else Path(__file__).resolve().parent
    )
    version = source_version(source)

    root = home / ".expert-workstation"
    versions = root / "versions"
    destination = versions / version
    active_file = root / "active-version"
    previous_file = root / "previous-version"
    launcher = home / "bin" / "xp"

    versions.mkdir(parents=True, exist_ok=True)
    launcher.parent.mkdir(parents=True, exist_ok=True)

    legacy_runner = home / "bin" / "ai-task-run"
    legacy_before = legacy_runner.read_bytes() if legacy_runner.is_file() else None

    current = (
        active_file.read_text(encoding="utf-8").strip()
        if active_file.is_file()
        else None
    )

    if destination.exists():
        installed_version = source_version(destination)
        if installed_version != version:
            raise RuntimeError(
                f"existing engine directory has wrong version: "
                f"{installed_version!r} != {version!r}"
            )
    else:
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{version}.install-",
                dir=str(versions),
            )
        )
        try:
            shutil.rmtree(staging)
            _copy_source(source, staging)
            if source_version(staging) != version:
                raise RuntimeError("staged engine version mismatch")
            os.replace(staging, destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    launcher.write_text(_launcher_text(), encoding="utf-8")
    launcher.chmod(
        launcher.stat().st_mode
        | stat.S_IXUSR
        | stat.S_IXGRP
        | stat.S_IXOTH
    )

    if current and current != version:
        current_dir = versions / current
        if not current_dir.is_dir():
            raise RuntimeError(
                f"active engine directory missing before install: {current}"
            )
        _atomic_text(previous_file, current + "\n")

    _atomic_text(active_file, version + "\n")

    bashrc = home / ".bashrc"
    path_line = 'export PATH="$HOME/bin:$PATH"'
    existing = bashrc.read_text(encoding="utf-8") if bashrc.is_file() else ""
    if path_line not in existing.splitlines():
        prefix = existing.rstrip()
        bashrc.write_text(
            (prefix + "\n" if prefix else "") + path_line + "\n",
            encoding="utf-8",
        )

    if legacy_before is not None:
        if not legacy_runner.is_file() or legacy_runner.read_bytes() != legacy_before:
            raise RuntimeError("legacy ai-task-run was modified by XP installer")

    return destination


def main() -> int:
    destination = install_into(Path.home())
    version = source_version(destination)
    print("=== Expert Workstation XP+ Installer ===")
    print(f"Installed version: {version}")
    print(f"Engine path      : {destination}")
    print("Launcher         : ~/bin/xp")
    print("Run: xp version")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
