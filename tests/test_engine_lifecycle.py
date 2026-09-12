from __future__ import annotations

import importlib
import importlib.util
import tempfile
import unittest
from pathlib import Path


class EngineLifecycleRedTests(unittest.TestCase):
    def _load_api(self):
        spec = importlib.util.find_spec("xp.engine_lifecycle")
        self.assertIsNotNone(
            spec,
            "XP+-01 RED: src/xp/engine_lifecycle.py does not exist yet",
        )
        module = importlib.import_module("xp.engine_lifecycle")
        lifecycle_cls = getattr(module, "EngineLifecycle", None)
        self.assertIsNotNone(
            lifecycle_cls,
            "XP+-01 RED: EngineLifecycle API is not implemented yet",
        )
        return lifecycle_cls

    @staticmethod
    def _candidate_source(root: Path, version: str) -> Path:
        source = root / f"candidate-{version}"
        package = source / "src" / "xp"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(
            f'__version__ = "{version}"\n',
            encoding="utf-8",
        )
        return source

    def test_install_candidate_is_side_by_side_and_does_not_switch_active_version(self):
        EngineLifecycle = self._load_api()

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            root = home / ".expert-workstation"
            root.mkdir(parents=True)
            (root / "active-version").write_text("2.0.0-rc18.3\n", encoding="utf-8")

            candidate_source = self._candidate_source(home, "2.1.0-rc1")
            lifecycle = EngineLifecycle(home)

            result = lifecycle.install_candidate("2.1.0-rc1", candidate_source)

            self.assertEqual(result.status, "INSTALLED")
            self.assertEqual(lifecycle.active_version(), "2.0.0-rc18.3")
            self.assertEqual(lifecycle.candidate_version(), "2.1.0-rc1")
            self.assertTrue(
                (root / "versions" / "2.1.0-rc1" / "src" / "xp" / "__init__.py").is_file()
            )
            self.assertFalse((root / "previous-version").exists())

    def test_activation_records_previous_before_switching_active_version(self):
        EngineLifecycle = self._load_api()

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            root = home / ".expert-workstation"
            root.mkdir(parents=True)
            (root / "active-version").write_text("2.0.0-rc18.3\n", encoding="utf-8")

            lifecycle = EngineLifecycle(home)
            candidate_source = self._candidate_source(home, "2.1.0-rc1")
            lifecycle.install_candidate("2.1.0-rc1", candidate_source)

            result = lifecycle.activate_candidate("2.1.0-rc1")

            self.assertEqual(result.status, "ACTIVATED")
            self.assertEqual(lifecycle.previous_version(), "2.0.0-rc18.3")
            self.assertEqual(lifecycle.active_version(), "2.1.0-rc1")
            self.assertIsNone(lifecycle.candidate_version())

    def test_failed_post_activation_health_check_rolls_back_to_previous_version(self):
        EngineLifecycle = self._load_api()

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            root = home / ".expert-workstation"
            root.mkdir(parents=True)
            (root / "active-version").write_text("2.0.0-rc18.3\n", encoding="utf-8")

            lifecycle = EngineLifecycle(home)
            candidate_source = self._candidate_source(home, "2.1.0-rc1")
            lifecycle.install_candidate("2.1.0-rc1", candidate_source)

            observed_active = []

            def failing_health_check(candidate_path: Path) -> bool:
                observed_active.append(lifecycle.active_version())
                self.assertTrue(candidate_path.is_dir())
                return False

            result = lifecycle.activate_with_health_check(
                "2.1.0-rc1",
                health_check=failing_health_check,
            )

            self.assertEqual(observed_active, ["2.1.0-rc1"])
            self.assertEqual(result.status, "ROLLED_BACK")
            self.assertEqual(lifecycle.active_version(), "2.0.0-rc18.3")
            self.assertEqual(lifecycle.previous_version(), "2.0.0-rc18.3")
            self.assertIsNone(lifecycle.candidate_version())

    def test_health_check_exception_rolls_back_before_error_is_re_raised(self):
        EngineLifecycle = self._load_api()

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            root = home / ".expert-workstation"
            root.mkdir(parents=True)
            (root / "active-version").write_text("2.0.0-rc18.3\n", encoding="utf-8")

            lifecycle = EngineLifecycle(home)
            candidate_source = self._candidate_source(home, "2.1.0-rc1")
            lifecycle.install_candidate("2.1.0-rc1", candidate_source)

            class CandidateHealthError(RuntimeError):
                pass

            def exploding_health_check(candidate_path: Path) -> bool:
                self.assertEqual(lifecycle.active_version(), "2.1.0-rc1")
                self.assertTrue(candidate_path.is_dir())
                raise CandidateHealthError("candidate health check exploded")

            with self.assertRaisesRegex(
                CandidateHealthError,
                "candidate health check exploded",
            ):
                lifecycle.activate_with_health_check(
                    "2.1.0-rc1",
                    health_check=exploding_health_check,
                )

            self.assertEqual(
                lifecycle.active_version(),
                "2.0.0-rc18.3",
                "XP+-01 RED #4: active version must be restored even when health check raises",
            )
            self.assertEqual(lifecycle.previous_version(), "2.0.0-rc18.3")
            self.assertIsNone(lifecycle.candidate_version())


if __name__ == "__main__":
    unittest.main()
