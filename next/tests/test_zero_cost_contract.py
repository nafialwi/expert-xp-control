from __future__ import annotations
import json
from pathlib import Path
import unittest

FIXTURE = Path(__file__).parent / "fixtures" / "zero_cost_independence.json"

class ZeroCostIndependenceContractTests(unittest.TestCase):
    def test_fixture_forbids_mandatory_chatgpt_cloud_and_paid_api(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        env = data["required_environment"]
        self.assertFalse(env["chatgpt_available"])
        self.assertFalse(env["paid_api_available"])
        self.assertFalse(env["router9_available"])
        self.assertFalse(env["internet_required"])
        self.assertTrue(env["local_qwen_required"])
        self.assertTrue(env["hermes_required"])
        self.assertIn("mandatory_cloud", data["forbidden_dependencies"])
        self.assertIn("WAITING_GPT", data["forbidden_dependencies"])

    def test_fixture_requires_review_before_apply_or_discard(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        flow = data["required_flow"]
        self.assertLess(flow.index("run_verifier"), flow.index("present_review"))
        self.assertLess(flow.index("present_review"), flow.index("apply_or_discard"))

if __name__ == "__main__":
    unittest.main()
