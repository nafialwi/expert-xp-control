from __future__ import annotations

import ast
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from xp.compatibility_audit import find_legacy_upgrade_stray_artifacts
from xp.readiness import audit_workstation


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "tools" / "xp_rc183_bootstrap.py"
BASE = "2.0.0-rc18.3"
STABLE = "2.1.0"
BOOTSTRAP_ASSET = "xp-rc183-to-210-bootstrap.py"
ENGINE_ASSET = "XP_PLUS_2.1.0_ENGINE.zip"
CHECKSUM_ASSET = "SHA256SUMS.txt"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda p: p.as_posix()):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode() + b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _copy_engine(target: Path, version: str):
    shutil.copytree(
        ROOT,
        target,
        symlinks=True,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".pytest_cache"),
    )
    init_file = target / "src" / "xp" / "__init__.py"
    text = init_file.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'__version__\s*=\s*["\'][^"\']+["\']',
        f'__version__ = "{version}"',
        text,
        count=1,
    )
    if count != 1:
        raise RuntimeError("cannot set fixture version")
    init_file.write_text(updated, encoding="utf-8")


def _zip_repo(target: Path):
    skip = {".git", "__pycache__", ".pytest_cache"}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(ROOT.rglob("*"), key=lambda p: p.as_posix()):
            if any(part in skip for part in path.parts) or path.suffix == ".pyc":
                continue
            if path.is_file():
                zf.write(path, path.relative_to(ROOT).as_posix())


def _seed_home(home: Path):
    root = home / ".expert-workstation"
    (root / "versions").mkdir(parents=True, exist_ok=True)
    _copy_engine(root / "versions" / BASE, BASE)
    (root / "active-version").write_text(BASE + "\n", encoding="utf-8")
    return root


def _make_assets(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / BOOTSTRAP_ASSET
    shutil.copy2(BOOTSTRAP, script)
    archive = directory / ENGINE_ASSET
    _zip_repo(archive)
    sums = directory / CHECKSUM_ASSET
    sums.write_text(
        f"{_sha(script)}  {BOOTSTRAP_ASSET}\n"
        f"{_sha(archive)}  {ENGINE_ASSET}\n",
        encoding="utf-8",
    )
    return script, archive, sums


def _run_bootstrap(script: Path, home: Path):
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["XP_USER_HOME"] = str(home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=script.parent,
        env=env,
        text=True,
        capture_output=True,
    )


def _rollback(home: Path):
    stable = home / ".expert-workstation" / "versions" / STABLE
    code = (
        "from pathlib import Path\n"
        "import os\n"
        "from xp.engine_lifecycle import EngineLifecycle\n"
        "home=Path(os.environ['XP_USER_HOME'])\n"
        "l=EngineLifecycle(home)\n"
        "l.rollback_to_previous(reason='xp10-bootstrap-regression')\n"
        "print(l.active_version())\n"
        "print(l.previous_version())\n"
        "print(l.candidate_version())\n"
    )
    env = os.environ.copy()
    env["XP_USER_HOME"] = str(home)
    env["HOME"] = str(home)
    env["PYTHONPATH"] = str(stable / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=home,
        env=env,
        text=True,
        capture_output=True,
    )


class Rc183BootstrapTests(unittest.TestCase):
    def test_bootstrap_source_is_thin_stdlib_and_has_no_activation_implementation(self):
        source = BOOTSTRAP.read_text(encoding="utf-8")
        tree = ast.parse(source)
        allowed = {
            "argparse", "hashlib", "os", "re", "shutil", "subprocess",
            "sys", "tempfile", "time", "zipfile", "pathlib", "__future__",
        }
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        self.assertTrue(imports <= allowed, imports - allowed)
        self.assertNotIn("/data/data/", source)
        self.assertNotIn("nafialwi", source)
        self.assertNotIn("_switch_active_version", source)
        self.assertNotIn(".activate_candidate(", source)
        self.assertNotIn("rollback_to_previous(", source)
        self.assertNotIn("os.replace(", source)
        self.assertIn("ENGINE_LIFECYCLE_INSTALL: PASS", source)
        self.assertIn(".install_candidate(", source)
        self.assertIn("activate_with_health_check", source)
        self.assertIn("result=lifecycle.activate_with_health_check(version)", source)
        self.assertNotIn("health_check=", source)
        self.assertNotIn("inspect.signature", source)
        self.assertNotIn("stable_health_check", source)

    def test_bootstrap_uses_engine_default_health_authority(self):
        source = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn(
            "result=lifecycle.activate_with_health_check(version)\\n",
            source,
        )
        self.assertNotIn("health_check=", source)
        self.assertNotIn("lifecycle.health_check", source)

    def test_compatibility_audit_reports_legacy_strays_without_deleting(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            home.mkdir()
            stray_active = home / "active-version"
            stray_versions = home / "versions"
            stray_active.write_text("2.1.0\n", encoding="utf-8")
            (stray_versions / "2.1.0").mkdir(parents=True)
            found = find_legacy_upgrade_stray_artifacts(home)
            self.assertEqual(
                {item.path for item in found},
                {stray_active, stray_versions},
            )
            report = audit_workstation(home, check_database_connection=False)
            checks = {check.code: check for check in report.checks}
            self.assertIn("LEGACY_UPGRADE_STRAY_ARTIFACTS", checks)
            self.assertEqual(checks["LEGACY_UPGRADE_STRAY_ARTIFACTS"].level, "INFO")
            self.assertIn("REPORT-ONLY", checks["LEGACY_UPGRADE_STRAY_ARTIFACTS"].detail)
            self.assertTrue(stray_active.exists())
            self.assertTrue(stray_versions.exists())

    def test_user_exact_bootstrap_upgrades_and_a_rb_rolls_back_without_touching_rc183(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            home = base / "home"
            home.mkdir()
            root = _seed_home(home)
            base_engine = root / "versions" / BASE
            before = _tree_hash(base_engine)
            (home / "active-version").write_text("2.1.0\n", encoding="utf-8")
            (home / "versions" / "2.1.0").mkdir(parents=True)
            script, _archive, _sums = _make_assets(base / "assets")

            result = _run_bootstrap(script, home)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("LEGACY STRAY     : REPORT-ONLY", result.stdout)
            self.assertEqual((root / "active-version").read_text().strip(), STABLE)
            self.assertEqual((root / "previous-version").read_text().strip(), BASE)
            self.assertFalse((root / "candidate-version").exists())
            self.assertEqual(_tree_hash(base_engine), before)
            self.assertTrue((home / "active-version").exists())
            self.assertTrue((home / "versions").exists())

            rollback = _rollback(home)
            self.assertEqual(rollback.returncode, 0, rollback.stdout + rollback.stderr)
            lines = [line.strip() for line in rollback.stdout.splitlines() if line.strip()]
            self.assertGreaterEqual(len(lines), 3)
            self.assertEqual(lines[-3], BASE)
            self.assertEqual(lines[-2], STABLE)
            self.assertEqual(lines[-1], "None")
            self.assertEqual(_tree_hash(base_engine), before)

    def test_interrupted_after_install_is_rerunnable(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            home = base / "home"
            home.mkdir()
            root = _seed_home(home)
            before = _tree_hash(root / "versions" / BASE)
            script, _archive, _sums = _make_assets(base / "assets")

            # Simulate interruption immediately after the lifecycle has staged the
            # candidate but before activation. No production test hook is used.
            spec = importlib.util.spec_from_file_location("xp_rc183_bootstrap_test", script)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with tempfile.TemporaryDirectory() as extract_td:
                source = Path(extract_td) / "engine"
                source.mkdir()
                module._safe_extract(base / "assets" / ENGINE_ASSET, source)
                module._prepare_candidate(source, home)

            self.assertEqual((root / "active-version").read_text().strip(), BASE)
            self.assertEqual((root / "candidate-version").read_text().strip(), STABLE)

            second = _run_bootstrap(script, home)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertIn("existing complete 2.1.0 candidate will be resumed", second.stdout)
            self.assertEqual((root / "active-version").read_text().strip(), STABLE)
            self.assertEqual((root / "previous-version").read_text().strip(), BASE)
            self.assertFalse((root / "candidate-version").exists())
            self.assertEqual(_tree_hash(root / "versions" / BASE), before)


if __name__ == "__main__":
    unittest.main()
