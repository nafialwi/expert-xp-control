from __future__ import annotations

import ast
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from xp.cli import _upgrade_cmd
from xp.engine_lifecycle import EngineHealthReport, EngineLifecycle


ROOT = Path(__file__).resolve().parents[1]
BASE = "2.0.0-rc18.3"
STABLE = "2.1.0"


def _run(cmd, cwd: Path):
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=True)


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if ".git" in path.parts or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode() + b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _seed_home(home: Path):
    root = home / ".expert-workstation"
    base = root / "versions" / BASE / "src" / "xp"
    base.mkdir(parents=True)
    (base / "__init__.py").write_text(f'__version__ = "{BASE}"\n', encoding="utf-8")
    (root / "active-version").write_text(BASE + "\n", encoding="utf-8")
    return root


@contextmanager
def _environment(**updates):
    before = os.environ.copy()
    try:
        os.environ.update({key: str(value) for key, value in updates.items()})
        yield
    finally:
        os.environ.clear()
        os.environ.update(before)


def _build_broken_remote(root: Path, version: str) -> Path:
    remote = root / "remote.git"
    seed = root / "seed"
    seed.mkdir()
    _run(["git", "init"], seed)
    _run(["git", "checkout", "-b", "xp-engine"], seed)
    _run(["git", "config", "user.email", "xp-health@example.invalid"], seed)
    _run(["git", "config", "user.name", "XP Health Test"], seed)

    package = seed / "src" / "xp"
    tests = seed / "tests"
    package.mkdir(parents=True)
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    (package / "cli.py").write_text(
        "from . import __version__\n"
        "import sys\n"
        "def main():\n"
        "    if sys.argv[1:] == ['version']:\n"
        "        print(f'Expert Workstation XP {__version__}')\n"
        "        return 0\n"
        "    return 2\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n",
        encoding="utf-8",
    )
    (tests / "test_backward_compatibility.py").write_text(
        "import unittest\n"
        "class Compat(unittest.TestCase):\n"
        "    def test_v1(self): self.assertTrue(True)\n",
        encoding="utf-8",
    )
    # Intentionally omit xp.schema/xp.compatibility/self-test support. This candidate
    # passes the legacy preflight, then must fail the DEFAULT post-activation health authority.
    _run(["git", "add", "."], seed)
    _run(["git", "commit", "-m", "broken post-health candidate"], seed)
    _run(["git", "init", "--bare", str(remote)], root)
    _run(["git", "remote", "add", "origin", str(remote)], seed)
    _run(["git", "push", "-u", "origin", "xp-engine"], seed)
    return remote


class XP10HealthAuthorityTests(unittest.TestCase):
    def test_default_health_authority_returns_structured_records_and_preserves_project_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            project = root / "project"
            home.mkdir()
            project.mkdir()
            marker = project / "source.txt"
            marker.write_text("immutable project source\n", encoding="utf-8")
            project_before = _tree_hash(project)
            _seed_home(home)

            lifecycle = EngineLifecycle(home)
            lifecycle.install_candidate(STABLE, ROOT)
            result = lifecycle.activate_with_health_check(STABLE)

            self.assertEqual(result.status, "ACTIVATED")
            self.assertIsInstance(result.health, EngineHealthReport)
            self.assertTrue(result.health.ok, result.health.checks)
            statuses = result.health.status_map()
            for code in (
                "candidate-import-integrity",
                "cli-startup",
                "schema-reader",
                "registry-state-readability",
                "no-mutation-self-test",
            ):
                self.assertEqual(statuses.get(code), "CLEAR", statuses)
            self.assertEqual(project_before, _tree_hash(project))
            self.assertEqual(lifecycle.active_version(), STABLE)
            self.assertEqual(lifecycle.previous_version(), BASE)

    def test_real_cli_upgrade_broken_candidate_rolls_back_through_default_health_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            home.mkdir()
            xp_root = _seed_home(home)
            remote = _build_broken_remote(root, "2.1.0-broken-health")
            engine = xp_root / "engine"
            _run(["git", "clone", "-b", "xp-engine", str(remote), str(engine)], root)

            with _environment(XP_USER_HOME=home, XP_ENGINE_BRANCH="xp-engine"):
                rc = _upgrade_cmd()

            self.assertEqual(rc, 1)
            self.assertEqual((xp_root / "active-version").read_text().strip(), BASE)
            self.assertEqual(
                (xp_root / "previous-version").read_text().strip(),
                "2.1.0-broken-health",
            )
            self.assertFalse((xp_root / "candidate-version").exists())
            journal = xp_root / "engine-rollback-journal.jsonl"
            self.assertTrue(journal.is_file())
            self.assertIn("post-activation-health-failed", journal.read_text(encoding="utf-8"))

    def test_production_call_sites_do_not_inject_health_semantics(self):
        offenders = []
        for path in sorted((ROOT / "src").rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "activate_with_health_check":
                    if any(keyword.arg == "health_check" for keyword in node.keywords):
                        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual(offenders, [], offenders)


if __name__ == "__main__":
    unittest.main()
