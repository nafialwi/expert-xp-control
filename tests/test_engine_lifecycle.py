from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xp.engine_lifecycle import EngineLifecycle


class EngineLifecycleTests(unittest.TestCase):
    @staticmethod
    def _candidate_source(root: Path, version: str, *, compat_pass: bool = True) -> Path:
        source = root / f"candidate-{version}"
        package = source / "src" / "xp"
        tests = source / "tests"
        package.mkdir(parents=True)
        tests.mkdir(parents=True)

        (tests / "__init__.py").write_text("", encoding="utf-8")
        (package / "__init__.py").write_text(
            f'__version__ = "{version}"\n',
            encoding="utf-8",
        )
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
            "    def test_v1(self):\n"
            f"        self.assertTrue({compat_pass!r})\n",
            encoding="utf-8",
        )
        return source

    @staticmethod
    def _lifecycle(td: str):
        home = Path(td)
        root = home / ".expert-workstation"
        root.mkdir(parents=True)
        (root / "active-version").write_text("2.0.0-rc18.3\n", encoding="utf-8")
        return EngineLifecycle(home), root

    def test_install_candidate_is_side_by_side_and_does_not_switch_active_version(self):
        with tempfile.TemporaryDirectory() as td:
            lifecycle, root = self._lifecycle(td)
            lifecycle.install_candidate(
                "2.1.0-rc1",
                self._candidate_source(Path(td), "2.1.0-rc1"),
            )
            self.assertEqual(lifecycle.active_version(), "2.0.0-rc18.3")
            self.assertEqual(lifecycle.candidate_version(), "2.1.0-rc1")
            self.assertTrue(
                (root / "versions" / "2.1.0-rc1" / "src" / "xp" / "__init__.py").is_file()
            )
            self.assertFalse((root / "previous-version").exists())

    def test_activation_records_previous_before_switching(self):
        with tempfile.TemporaryDirectory() as td:
            lifecycle, _ = self._lifecycle(td)
            lifecycle.install_candidate(
                "2.1.0-rc1",
                self._candidate_source(Path(td), "2.1.0-rc1"),
            )
            result = lifecycle.activate_candidate("2.1.0-rc1")
            self.assertEqual(result.status, "ACTIVATED")
            self.assertEqual(lifecycle.previous_version(), "2.0.0-rc18.3")
            self.assertEqual(lifecycle.active_version(), "2.1.0-rc1")
            self.assertIsNone(lifecycle.candidate_version())

    def test_false_health_check_rolls_back(self):
        with tempfile.TemporaryDirectory() as td:
            lifecycle, _ = self._lifecycle(td)
            lifecycle.install_candidate(
                "2.1.0-rc1",
                self._candidate_source(Path(td), "2.1.0-rc1"),
            )
            result = lifecycle.activate_with_health_check(
                "2.1.0-rc1",
                health_check=lambda _: False,
            )
            self.assertEqual(result.status, "ROLLED_BACK")
            self.assertEqual(lifecycle.active_version(), "2.0.0-rc18.3")

    def test_health_exception_rolls_back_then_reraises(self):
        with tempfile.TemporaryDirectory() as td:
            lifecycle, _ = self._lifecycle(td)
            lifecycle.install_candidate(
                "2.1.0-rc1",
                self._candidate_source(Path(td), "2.1.0-rc1"),
            )

            class Boom(RuntimeError):
                pass

            def explode(_):
                raise Boom("health exploded")

            with self.assertRaisesRegex(Boom, "health exploded"):
                lifecycle.activate_with_health_check(
                    "2.1.0-rc1",
                    health_check=explode,
                )
            self.assertEqual(lifecycle.active_version(), "2.0.0-rc18.3")

    def test_candidate_check_requires_import_cli_and_v1_compatibility(self):
        with tempfile.TemporaryDirectory() as td:
            lifecycle, _ = self._lifecycle(td)
            lifecycle.install_candidate(
                "2.1.0-rc1",
                self._candidate_source(Path(td), "2.1.0-rc1"),
            )
            report = lifecycle.check_candidate("2.1.0-rc1")
            self.assertEqual(report.status, "CLEAR", report.checks)
            self.assertEqual(
                report.checks,
                {
                    "import": "CLEAR",
                    "cli-version": "CLEAR",
                    "compat-v1": "CLEAR",
                },
            )

    def test_failed_compatibility_fixture_blocks_promotion_before_activation(self):
        with tempfile.TemporaryDirectory() as td:
            lifecycle, _ = self._lifecycle(td)
            lifecycle.install_candidate(
                "2.1.0-rc1",
                self._candidate_source(Path(td), "2.1.0-rc1", compat_pass=False),
            )
            result = lifecycle.promote_candidate("2.1.0-rc1")
            self.assertEqual(result.status, "BLOCKED")
            self.assertEqual(result.checks["compat-v1"], "BLOCKED")
            self.assertEqual(lifecycle.active_version(), "2.0.0-rc18.3")
            self.assertEqual(lifecycle.candidate_version(), "2.1.0-rc1")
            self.assertIsNone(lifecycle.previous_version())

    def test_healthy_candidate_is_promoted_after_pre_and_post_checks(self):
        with tempfile.TemporaryDirectory() as td:
            lifecycle, _ = self._lifecycle(td)
            lifecycle.install_candidate(
                "2.1.0-rc1",
                self._candidate_source(Path(td), "2.1.0-rc1"),
            )
            result = lifecycle.promote_candidate("2.1.0-rc1")
            self.assertEqual(result.status, "PROMOTED", result.checks)
            self.assertEqual(lifecycle.previous_version(), "2.0.0-rc18.3")
            self.assertEqual(lifecycle.active_version(), "2.1.0-rc1")
            self.assertIsNone(lifecycle.candidate_version())


if __name__ == "__main__":
    unittest.main()
