from __future__ import annotations

import ast
import inspect
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import xp.engine_lifecycle as lifecycle_module
from xp.engine_lifecycle import EngineLifecycle
from xp.paths import XPPaths
from xp.project_registry import ProjectRegistry, load_project_profile


ROOT = Path(__file__).resolve().parents[1]
BASE = "2.0.0-rc18.3"
RC = "2.1.0-rc1"


def _installed_engine_source(version: str) -> Path | None:
    user_home = Path(
        os.environ.get(
            "XP_USER_HOME",
            str(Path.home()),
        )
    ).expanduser().resolve()
    candidate = (
        user_home
        / ".expert-workstation"
        / "versions"
        / version
    )
    if (candidate / "src" / "xp" / "__init__.py").is_file():
        return candidate
    return None


def _copy_complete_engine_fixture(target: Path, version: str) -> str:
    source = _installed_engine_source(version)
    if source is not None:
        shutil.copytree(
            source,
            target,
            symlinks=True,
        )
        return "real-installed-copy"

    # Portable fallback for environments that do not already have rc18.3
    # installed. Reproduce a complete engine installation shape from the
    # repository instead of the old fake directory containing BASELINE.txt.
    shutil.copytree(
        ROOT,
        target,
        symlinks=True,
        ignore=shutil.ignore_patterns(
            ".git",
            "__pycache__",
            "*.pyc",
            ".pytest_cache",
        ),
    )
    init_file = target / "src" / "xp" / "__init__.py"
    if not init_file.is_file():
        raise RuntimeError(
            "portable baseline fixture lacks src/xp/__init__.py"
        )
    current = init_file.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'__version__\s*=\s*["\'][^"\']+["\']',
        f'__version__ = "{version}"',
        current,
        count=1,
    )
    if count != 1:
        raise RuntimeError(
            "portable baseline fixture could not set engine version"
        )
    init_file.write_text(updated, encoding="utf-8")
    return "portable-complete-copy"


def _seed_active(home: Path, version: str = BASE):
    paths = XPPaths.from_home(home)
    paths.ensure_runtime_dirs()
    target = paths.versions / version
    if target.exists():
        shutil.rmtree(target)
    fixture_kind = _copy_complete_engine_fixture(
        target,
        version,
    )
    if not (target / "src" / "xp" / "__init__.py").is_file():
        raise RuntimeError(
            f"complete engine fixture missing for {version}"
        )
    (
        paths.root
        / "active-version"
    ).write_text(
        version + "\n",
        encoding="utf-8",
    )
    return paths, fixture_kind


def _seed_registry_and_checkpoint(home: Path):
    repo = (
        ROOT
        / "tests"
        / "fixtures"
        / "plain-git"
    )
    profile = load_project_profile(repo)
    registry = ProjectRegistry.for_home(home)
    registry.register(
        profile,
        repo,
    )

    fixture = (
        ROOT
        / "tests"
        / "fixtures"
        / "checkpoint_v1"
        / "CHECKPOINT_STATE.json"
    )
    if not fixture.is_file():
        raise RuntimeError(
            "checkpoint v1 fixture missing"
        )

    target = (
        Path(home)
        / ".expert-workstation"
        / "checkpoints"
        / profile.project_id
        / "XP08-ARB"
        / "CHECKPOINT_STATE.json"
    )
    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    shutil.copy2(
        fixture,
        target,
    )
    return registry, target


def _read_checkpoint(path: Path):
    from xp.checkpoint import (
        read_checkpoint_state_v1,
    )

    try:
        return read_checkpoint_state_v1(path)
    except (TypeError, AttributeError):
        return read_checkpoint_state_v1(
            json.loads(
                path.read_text(
                    encoding="utf-8",
                )
            )
        )


def _function_map(source: str):
    tree = ast.parse(source)
    functions = {}

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            functions[node.name] = node

        if (
            isinstance(node, ast.ClassDef)
            and node.name == "EngineLifecycle"
        ):
            for child in node.body:
                if isinstance(
                    child,
                    ast.FunctionDef,
                ):
                    functions[
                        child.name
                    ] = child

    return functions


def _calls_os_replace(
    source: str,
    start: str,
) -> bool:
    functions = _function_map(source)
    seen = set()

    def visit(name: str) -> bool:
        if (
            name in seen
            or name not in functions
        ):
            return False

        seen.add(name)
        node = functions[name]
        callees = set()

        for child in ast.walk(node):
            if not isinstance(
                child,
                ast.Call,
            ):
                continue

            func = child.func

            if (
                isinstance(func, ast.Attribute)
                and isinstance(
                    func.value,
                    ast.Name,
                )
                and func.value.id == "os"
                and func.attr == "replace"
            ):
                return True

            if (
                isinstance(func, ast.Attribute)
                and isinstance(
                    func.value,
                    ast.Name,
                )
                and func.value.id == "self"
            ):
                callees.add(
                    func.attr
                )
            elif isinstance(
                func,
                ast.Name,
            ):
                callees.add(
                    func.id
                )

        return any(
            visit(callee)
            for callee in callees
        )

    return visit(start)


class ARBRollbackLifecycleTests(
    unittest.TestCase
):
    def test_full_real_temp_home_promotion_and_rollback_sequence(self):
        self.assertTrue(
            hasattr(
                EngineLifecycle,
                "_switch_active_version",
            )
        )
        self.assertTrue(
            hasattr(
                EngineLifecycle,
                "rollback_to_previous",
            )
        )

        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            paths, baseline_fixture = _seed_active(home)
            (
                registry,
                checkpoint,
            ) = _seed_registry_and_checkpoint(
                home
            )
            registry_before = (
                registry.export_data()
            )
            self.assertIn(
                baseline_fixture,
                {"real-installed-copy", "portable-complete-copy"},
            )
            self.assertTrue(
                (
                    paths.versions
                    / BASE
                    / "src"
                    / "xp"
                    / "__init__.py"
                ).is_file()
            )

            lifecycle = EngineLifecycle(home)
            lifecycle.install_candidate(
                RC,
                ROOT,
            )

            self.assertEqual(
                lifecycle.active_version(),
                BASE,
            )
            self.assertEqual(
                lifecycle.candidate_version(),
                RC,
            )

            lifecycle.activate_candidate(
                RC
            )

            self.assertEqual(
                lifecycle.active_version(),
                RC,
            )
            self.assertEqual(
                lifecycle.previous_version(),
                BASE,
            )
            self.assertIsNone(
                lifecycle.candidate_version()
            )

            lifecycle.rollback_to_previous(
                reason="xp08-a-rb-integration"
            )

            self.assertEqual(
                lifecycle.active_version(),
                BASE,
            )
            self.assertEqual(
                lifecycle.previous_version(),
                RC,
            )
            self.assertIsNone(
                lifecycle.candidate_version()
            )
            self.assertTrue(
                (
                    paths.versions
                    / RC
                ).is_dir()
            )

            self.assertEqual(
                ProjectRegistry.for_home(
                    home
                ).export_data(),
                registry_before,
            )
            self.assertIsNotNone(
                _read_checkpoint(
                    checkpoint
                )
            )

            journal = (
                paths.root
                / "engine-rollback-journal.jsonl"
            )
            self.assertTrue(
                journal.is_file()
            )

            rows = [
                json.loads(line)
                for line in journal.read_text(
                    encoding="utf-8"
                ).splitlines()
                if line.strip()
            ]

            self.assertTrue(rows)
            event = rows[-1]

            self.assertEqual(
                event["version"],
                RC,
            )
            self.assertEqual(
                event["reason"],
                "xp08-a-rb-integration",
            )
            self.assertTrue(
                event["timestamp"]
            )

    def test_activate_candidate_wrong_version_hard_stops(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            _seed_active(home)
            lifecycle = EngineLifecycle(home)
            lifecycle.install_candidate(
                RC,
                ROOT,
            )

            with self.assertRaisesRegex(
                ValueError,
                "candidate mismatch",
            ):
                lifecycle.activate_candidate(
                    "9.9.9-wrong"
                )

    def test_rollback_without_previous_version_hard_stops(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            _seed_active(home)
            lifecycle = EngineLifecycle(home)

            with self.assertRaisesRegex(
                RuntimeError,
                "previous",
            ):
                lifecycle.rollback_to_previous(
                    reason="missing-previous"
                )

    def test_rollback_missing_previous_engine_hard_stops(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            paths, _fixture_kind = _seed_active(
                home,
                RC,
            )
            (
                paths.root
                / "previous-version"
            ).write_text(
                BASE + "\n",
                encoding="utf-8",
            )

            lifecycle = EngineLifecycle(home)

            with self.assertRaisesRegex(
                (
                    FileNotFoundError,
                    RuntimeError,
                ),
                "previous|installed|engine",
            ):
                lifecycle.rollback_to_previous(
                    reason="missing-engine"
                )

    def test_both_entry_points_share_private_switch(self):
        public = inspect.getsource(
            EngineLifecycle.activate_candidate
        )
        rollback = inspect.getsource(
            EngineLifecycle.rollback_to_previous
        )

        self.assertIn(
            "self._switch_active_version",
            public,
        )
        self.assertIn(
            "self._switch_active_version",
            rollback,
        )
        self.assertNotIn(
            "self.activate_candidate",
            rollback,
        )

    def test_switch_path_is_atomic_via_os_replace(self):
        source = inspect.getsource(
            lifecycle_module
        )

        self.assertTrue(
            _calls_os_replace(
                source,
                "_switch_active_version",
            ),
            (
                "shared switch path must reach "
                "os.replace through its real call graph"
            ),
        )


if __name__ == "__main__":
    unittest.main()
