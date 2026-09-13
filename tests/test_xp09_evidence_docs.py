from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / 'docs' / 'XP_PLUS_COMPATIBILITY_MATRIX.md'
UPGRADE = ROOT / 'docs' / 'XP_PLUS_UPGRADE_ROLLBACK.md'


class XP09EvidenceDocsTests(unittest.TestCase):
    def test_matrix_contains_binding_s2_evidence_rows(self):
        text = MATRIX.read_text(encoding='utf-8')
        required = [
            '§14-1 Plain Git',
            '§14-2 Node',
            '§14-3 Python',
            '§14-4 Node + PostgreSQL',
            '§14-5 Firebase/static',
            '§14-6 Legacy',
            '§14-7 Next',
            'Zone 1 Legacy',
            'Zone 1 Next',
            'Zone 2 Legacy',
            'Zone 2 Next',
            'Copy-home drill',
            'Clean-install RC commit',
            'rc18.3 -> 2.1.0 projected upgrade',
            'Failed-candidate automatic rollback',
            'Installed-candidate shadow',
        ]
        for label in required:
            self.assertIn(label, text)
        self.assertGreaterEqual(
            len(re.findall(r'\b[0-9a-f]{40}\b', text)),
            len(required),
        )
        self.assertGreaterEqual(
            len(re.findall(r'2026-[0-9]{2}-[0-9]{2}T[^|\n]+Z', text)),
            len(required),
        )

    def test_matrix_has_explicit_zone_columns(self):
        lines = MATRIX.read_text(encoding='utf-8').splitlines()
        header = next(line for line in lines if line.startswith('| ID |'))
        self.assertIn('Zone 1 Proof', header)
        self.assertIn('Zone 2 Proof', header)

    def test_upgrade_rollback_doc_records_a_rb_and_public_path_boundary(self):
        text = UPGRADE.read_text(encoding='utf-8')
        for phrase in (
            'A-RB',
            'rollback_to_previous',
            'previous-version',
            'candidate marker',
            'engine-rollback-journal.jsonl',
            'XP+-10',
            'public upgrade path',
        ):
            self.assertIn(phrase, text)


if __name__ == '__main__':
    unittest.main()
