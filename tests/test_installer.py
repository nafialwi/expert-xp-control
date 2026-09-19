from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import xp


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.py"


def _load_installer():
    spec = importlib.util.spec_from_file_location(
        "xp_release_installer_contract",
        INSTALLER,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InstallerContractTests(unittest.TestCase):
    def test_installer_derives_version_from_source_not_rc15_pin(self):
        text = INSTALLER.read_text(encoding="utf-8")
        shell = (ROOT / "installer.sh").read_text(encoding="utf-8")
        self.assertIn("XP_PLUS_CANONICAL_INSTALLER_V1", text)
        self.assertIn("XP_PLUS_INSTALLER_WRAPPER_V1", shell)
        self.assertNotIn("2.0.0-rc15", text)
        self.assertNotIn("2.0.0-rc15", shell)
        module = _load_installer()
        self.assertEqual(module.source_version(ROOT), xp.__version__)

    def test_fresh_install_preserves_legacy_runner_and_launcher_works(self):
        module = _load_installer()
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            legacy = home / "bin" / "ai-task-run"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("legacy-runner\n", encoding="utf-8")

            destination = module.install_into(home, ROOT)

            self.assertEqual(
                (home / ".expert-workstation" / "active-version")
                .read_text(encoding="utf-8")
                .strip(),
                xp.__version__,
            )
            self.assertTrue((destination / "src/xp/__init__.py").is_file())
            self.assertEqual(
                legacy.read_text(encoding="utf-8"),
                "legacy-runner\n",
            )

            launcher = home / "bin" / "xp"
            self.assertTrue(launcher.is_file())
            env = os.environ.copy()
            env["HOME"] = str(home)
            env["XP_USER_HOME"] = str(home)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env.pop("PYTHONPATH", None)

            for args in (
                ["version"],
                ["schema", "work"],
                ["self-test"],
            ):
                cp = subprocess.run(
                    [str(launcher), *args],
                    cwd=home,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=60,
                )
                self.assertEqual(cp.returncode, 0, f"{args}: {cp.stdout}")

    def test_install_records_previous_without_deleting_previous_engine(self):
        module = _load_installer()
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            root = home / ".expert-workstation"
            old = root / "versions" / "2.0.0-rc18.3"
            (old / "src/xp").mkdir(parents=True)
            (old / "src/xp/__init__.py").write_text(
                '__version__ = "2.0.0-rc18.3"\n',
                encoding="utf-8",
            )
            root.mkdir(parents=True, exist_ok=True)
            (root / "active-version").write_text(
                "2.0.0-rc18.3\n",
                encoding="utf-8",
            )

            module.install_into(home, ROOT)

            self.assertTrue(old.is_dir())
            self.assertEqual(
                (root / "previous-version").read_text().strip(),
                "2.0.0-rc18.3",
            )
            self.assertEqual(
                (root / "active-version").read_text().strip(),
                xp.__version__,
            )


if __name__ == "__main__":
    unittest.main()
