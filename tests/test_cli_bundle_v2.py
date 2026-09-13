from __future__ import annotations

import unittest

from xp.cli import build_parser


class BundleV2CLITests(unittest.TestCase):
    def test_bundle_defaults_compact_and_accepts_deep(self):
        parser = build_parser()

        compact = parser.parse_args(["bundle", "--repo", "/tmp/project"])
        self.assertFalse(compact.deep)

        deep = parser.parse_args(["bundle", "--repo", "/tmp/project", "--deep"])
        self.assertTrue(deep.deep)


if __name__ == "__main__":
    unittest.main()
