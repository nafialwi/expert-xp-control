from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FILES = (
    ROOT / "README.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "XP_PLUS_COMPATIBILITY_MATRIX.md",
    ROOT / "docs" / "XP_PLUS_UPGRADE_ROLLBACK.md",
)
PHRASES = (
    "rc18.3 built-in `xp upgrade` is defective",
    "outside the canonical `.expert-workstation`",
    "supported one-time path from rc18.3",
    "REPORT-ONLY",
    "explicit user approval",
    "origin >= 2.1.0",
)


class XP10BootstrapDocsTests(unittest.TestCase):
    def test_release_docs_state_rc183_defect_and_bootstrap_path_plainly(self):
        for path in FILES:
            self.assertTrue(path.is_file(), path)
            text = path.read_text(encoding="utf-8")
            for phrase in PHRASES:
                self.assertIn(phrase, text, f"{phrase!r} missing from {path}")


if __name__ == "__main__":
    unittest.main()
