#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

BASE_VERSION = "2.0.0-rc18.3"
STABLE_VERSION = "2.1.0"
BOOTSTRAP_ASSET = "xp-rc183-to-210-bootstrap.py"
ENGINE_ASSET = "XP_PLUS_2.1.0_ENGINE.zip"
CHECKSUM_ASSET = "SHA256SUMS.txt"


def _home() -> Path:
    value = os.environ.get("XP_USER_HOME")
    return Path(value).expanduser().resolve() if value else Path.home().resolve()


def _root(home: Path) -> Path:
    return home / ".expert-workstation"


def _read_marker(path: Path) -> str | None:
    if not path.is_file():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.is_dir():
        raise RuntimeError(f"engine directory missing: {root}")
    for path in sorted(root.rglob("*"), key=lambda p: p.as_posix()):
        rel = path.relative_to(root).as_posix()
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            digest.update(b"L\0" + rel.encode() + b"\0" + os.readlink(path).encode())
        elif path.is_file():
            digest.update(b"F\0" + rel.encode() + b"\0")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def _stray_inventory(home: Path) -> list[str]:
    canonical = _root(home)
    out: list[str] = []
    for path in (home / "active-version", home / "versions"):
        resolved = path.resolve(strict=False)
        if resolved == canonical or canonical in resolved.parents:
            continue
        if path.exists():
            out.append(str(path))
    return out


def _load_checksums(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise RuntimeError(f"checksum asset missing: {path}")
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            raise RuntimeError(f"invalid checksum line: {raw!r}")
        name = parts[1].lstrip("*").strip()
        result[name] = parts[0].lower()
    return result


def _verify_assets(script: Path, archive: Path, sums: Path) -> None:
    expected = _load_checksums(sums)
    for path, name in ((script, BOOTSTRAP_ASSET), (archive, ENGINE_ASSET)):
        wanted = expected.get(name)
        if not wanted:
            raise RuntimeError(f"checksum entry missing for {name}")
        actual = _sha256(path)
        if actual != wanted:
            raise RuntimeError(f"checksum mismatch for {name}: {actual} != {wanted}")
        print(f"CHECKSUM {name}: PASS {actual}")


def _safe_extract(archive: Path, destination: Path) -> None:
    root = destination.resolve()
    with zipfile.ZipFile(archive, "r") as zf:
        for info in zf.infolist():
            raw = info.filename.replace("\\", "/")
            if not raw or raw.startswith("/"):
                raise RuntimeError(f"unsafe archive member: {info.filename}")
            parts = Path(raw).parts
            if ".." in parts:
                raise RuntimeError(f"unsafe archive traversal: {info.filename}")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise RuntimeError(f"archive symlink is not allowed: {info.filename}")
            target = (destination / Path(*parts)).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError(f"archive escapes staging root: {info.filename}")
        for info in zf.infolist():
            target = destination / Path(*Path(info.filename.replace("\\", "/")).parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            perm = (info.external_attr >> 16) & 0o777
            if perm:
                try:
                    target.chmod(perm)
                except OSError:
                    pass


def _parse_source_version(source: Path) -> str:
    init_file = source / "src" / "xp" / "__init__.py"
    if not init_file.is_file():
        raise RuntimeError("engine archive missing src/xp/__init__.py")
    text = init_file.read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    if not match:
        raise RuntimeError("cannot parse engine version")
    return match.group(1)


def _run_stable_lifecycle_child(
    *,
    source_for_import: Path,
    home: Path,
    operation: str,
    candidate_source: Path | None = None,
) -> None:
    """Invoke XP+ lifecycle code in a child interpreter.

    The bootstrap itself remains stdlib-only. XP modules are imported only by
    the extracted/installed stable engine child process.
    """
    if operation not in {"install", "activate"}:
        raise RuntimeError(f"unsupported lifecycle child operation: {operation}")

    if operation == "install":
        code = (
            "from pathlib import Path\n"
            "import os\n"
            "from xp.engine_lifecycle import EngineLifecycle\n"
            "home=Path(os.environ['XP_BOOTSTRAP_HOME']).expanduser().resolve()\n"
            "version=os.environ['XP_BOOTSTRAP_VERSION']\n"
            "source=Path(os.environ['XP_BOOTSTRAP_SOURCE']).expanduser().resolve()\n"
            "lifecycle=EngineLifecycle(home)\n"
            "lifecycle.install_candidate(version, source)\n"
            "print('ENGINE_LIFECYCLE_INSTALL: PASS')\n"
            "print('ENGINE_LIFECYCLE_ACTIVE:', lifecycle.active_version())\n"
            "print('ENGINE_LIFECYCLE_CANDIDATE:', lifecycle.candidate_version())\n"
        )
    else:
        code = (
            "from pathlib import Path\n"
            "import os\n"
            "from xp.engine_lifecycle import EngineLifecycle\n"
            "home=Path(os.environ['XP_BOOTSTRAP_HOME']).expanduser().resolve()\n"
            "version=os.environ['XP_BOOTSTRAP_VERSION']\n"
            "lifecycle=EngineLifecycle(home)\n"
            "result=lifecycle.activate_with_health_check(version)\n"
            "print('ENGINE_LIFECYCLE_RESULT:', getattr(result, 'status', result))\n"
            "print('ENGINE_LIFECYCLE_ACTIVE:', lifecycle.active_version())\n"
            "print('ENGINE_LIFECYCLE_PREVIOUS:', lifecycle.previous_version())\n"
            "print('ENGINE_LIFECYCLE_CANDIDATE:', lifecycle.candidate_version())\n"
            "raise SystemExit(0 if lifecycle.active_version() == version else 9)\n"
        )

    env = os.environ.copy()
    env["XP_BOOTSTRAP_HOME"] = str(home)
    env["XP_BOOTSTRAP_VERSION"] = STABLE_VERSION
    env["XP_USER_HOME"] = str(home)
    env["PYTHONPATH"] = str(source_for_import / "src")
    if candidate_source is not None:
        env["XP_BOOTSTRAP_SOURCE"] = str(candidate_source)

    result = subprocess.run(
        [sys.executable, "-c", code],
        text=True,
        env=env,
        capture_output=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError(
            f"stable EngineLifecycle {operation} delegation failed "
            f"(rc={result.returncode})"
        )


def _delegate_install(source: Path, home: Path) -> None:
    _run_stable_lifecycle_child(
        source_for_import=source,
        home=home,
        operation="install",
        candidate_source=source,
    )


def _delegate_activation(installed: Path, home: Path) -> None:
    _run_stable_lifecycle_child(
        source_for_import=installed,
        home=home,
        operation="activate",
    )


def _prepare_candidate(source: Path, home: Path) -> Path:
    root = _root(home)
    versions = root / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    target = versions / STABLE_VERSION
    candidate_marker = _read_marker(root / "candidate-version")

    if candidate_marker and candidate_marker != STABLE_VERSION:
        raise RuntimeError(
            f"another candidate is pending: {candidate_marker}; refusing to interfere"
        )

    complete = (target / "src" / "xp" / "__init__.py").is_file()
    if candidate_marker == STABLE_VERSION and complete:
        print("CANDIDATE: existing complete 2.1.0 candidate will be resumed")
        return target

    if target.exists():
        quarantine = versions / (
            f"{STABLE_VERSION}.incomplete.{int(time.time())}.{os.getpid()}"
        )
        target.rename(quarantine)
        print(f"CANDIDATE: preserved incomplete prior attempt at {quarantine}")

    _delegate_install(source, home)
    if not (target / "src" / "xp" / "__init__.py").is_file():
        raise RuntimeError("EngineLifecycle install did not produce a complete candidate")
    print(f"CANDIDATE: staged side-by-side at {target}")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="One-time public upgrade bootstrap: XP 2.0.0-rc18.3 -> XP+ 2.1.0"
    )
    parser.add_argument("--archive", default=None)
    parser.add_argument("--checksums", default=None)
    args = parser.parse_args(argv)

    script = Path(__file__).resolve()
    asset_dir = script.parent
    archive = (
        Path(args.archive).expanduser().resolve()
        if args.archive
        else asset_dir / ENGINE_ASSET
    )
    sums = (
        Path(args.checksums).expanduser().resolve()
        if args.checksums
        else asset_dir / CHECKSUM_ASSET
    )

    home = _home()
    root = _root(home)
    active = _read_marker(root / "active-version")
    print("=== XP rc18.3 -> XP+ 2.1.0 bootstrap ===")
    print(f"HOME             : {home}")
    print(f"CANONICAL ROOT   : {root}")
    print(f"ACTIVE BEFORE    : {active or '-'}")
    stray = _stray_inventory(home)
    if stray:
        print("LEGACY STRAY     : REPORT-ONLY")
        for item in stray:
            print(f"  - {item}")
        print("LEGACY STRAY     : not deleted; cleanup requires explicit user approval")
    else:
        print("LEGACY STRAY     : none detected")

    if active == STABLE_VERSION:
        installed = root / "versions" / STABLE_VERSION
        if _parse_source_version(installed) != STABLE_VERSION:
            raise RuntimeError("2.1.0 is active but installed engine is incomplete")
        print("RESULT           : XP+ 2.1.0 already active; no action required")
        return 0
    if active != BASE_VERSION:
        raise RuntimeError(
            f"unsupported origin: active={active!r}; expected {BASE_VERSION}"
        )

    base_engine = root / "versions" / BASE_VERSION
    if not (base_engine / "src" / "xp" / "__init__.py").is_file():
        raise RuntimeError("canonical rc18.3 engine directory is missing/incomplete")
    base_hash_before = _tree_hash(base_engine)

    _verify_assets(script, archive, sums)

    tmp_parent = os.environ.get("TMPDIR")
    with tempfile.TemporaryDirectory(
        prefix="xp-rc183-bootstrap-",
        dir=tmp_parent if tmp_parent else None,
    ) as td:
        source = Path(td) / "engine"
        source.mkdir(parents=True)
        _safe_extract(archive, source)
        version = _parse_source_version(source)
        if version != STABLE_VERSION:
            raise RuntimeError(
                f"engine archive version={version!r}; expected {STABLE_VERSION}"
            )
        installed = _prepare_candidate(source, home)

        _delegate_activation(installed, home)

    active_after = _read_marker(root / "active-version")
    previous_after = _read_marker(root / "previous-version")
    candidate_after = _read_marker(root / "candidate-version")
    base_hash_after = _tree_hash(base_engine)

    print(f"ACTIVE AFTER     : {active_after or '-'}")
    print(f"PREVIOUS AFTER   : {previous_after or '-'}")
    print(f"CANDIDATE AFTER  : {candidate_after or '-'}")
    print(
        "RC18.3 DIRECTORY : "
        + ("UNCHANGED" if base_hash_before == base_hash_after else "CHANGED")
    )

    if active_after != STABLE_VERSION:
        raise RuntimeError("canonical active-version did not become 2.1.0")
    if previous_after != BASE_VERSION:
        raise RuntimeError("previous-version is not rc18.3 after activation")
    if candidate_after is not None:
        raise RuntimeError("candidate marker was not cleared after activation")
    if base_hash_before != base_hash_after:
        raise RuntimeError("rc18.3 engine directory changed during bootstrap")

    print("RESULT           : PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
