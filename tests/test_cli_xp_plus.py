from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout

from xp.cli import main


class XPPlusSchemaCLITests(unittest.TestCase):
    def _run(self, argv):
        output = io.StringIO()
        with redirect_stdout(output):
            rc = main(argv)
        return rc, output.getvalue()

    def test_schema_work_is_machine_readable(self):
        rc, output = self._run(["schema", "work"])
        self.assertEqual(rc, 0)
        data = json.loads(output)
        self.assertEqual(data["schema_name"], "work")
        self.assertEqual(data["operation_key"], "type")
        self.assertEqual(data["human_qa_key"], "human_qa")

    def test_schema_without_kind_prints_catalog(self):
        rc, output = self._run(["schema"])
        self.assertEqual(rc, 0)
        data = json.loads(output)
        self.assertEqual(set(data), {"work", "remediation", "project-profile"})
