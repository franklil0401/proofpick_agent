"""Interface fixtures only; no further real task is previewed or executed."""
import unittest

from .score_v2 import score_case_v2
from .test_harness import HarnessTests


class AdapterTests(unittest.TestCase):
    def setUp(self):
        f = HarnessTests()
        f.setUp()
        self.case, self.raw, self.catalog = f.case, f.raw, f.catalog

    def test_json_number(self):
        self.raw["response"]["report"]["evidence"][0]["value"] = "32.0"
        self.assertTrue(score_case_v2(self.case, self.raw, self.catalog)["passed"])

    def test_json_string(self):
        self.raw["response"]["report"]["evidence"][0]["value"] = '"US"'
        self.catalog["laptop"][0]["evidence"][0]["value"] = "US"
        self.assertTrue(score_case_v2(self.case, self.raw, self.catalog)["passed"])

    def test_null_reference_not_assertion_or_support(self):
        self.raw["response"]["report"]["evidence"][0]["value"] = None
        score = score_case_v2(self.case, self.raw, self.catalog)
        self.assertFalse(score["passed"])
        self.assertEqual(score["covered_fact_pairs"], 0)
        self.assertEqual(score["safety"], [])

    def test_null_reference_still_checks_identity(self):
        self.raw["response"]["report"]["evidence"][0].update(value=None, model_id="fictional-b")
        self.assertIn("invalid_evidence_binding", score_case_v2(self.case, self.raw, self.catalog)["safety"])

    def test_no_fuzzy_units(self):
        self.raw["response"]["report"]["evidence"][0]["value"] = "32 GB"
        self.assertIn("invalid_evidence_binding", score_case_v2(self.case, self.raw, self.catalog)["safety"])

    def test_boolean_not_number(self):
        self.raw["response"]["report"]["evidence"][0]["value"] = "true"
        self.catalog["laptop"][0]["evidence"][0]["value"] = 1
        self.assertIn("invalid_evidence_binding", score_case_v2(self.case, self.raw, self.catalog)["safety"])

    def test_wrong_value_still_rejected(self):
        self.raw["response"]["report"]["evidence"][0]["value"] = "64.0"
        self.assertFalse(score_case_v2(self.case, self.raw, self.catalog)["passed"])

    def test_original_result_not_mutated(self):
        node = self.raw["response"]["report"]["evidence"][0]
        node["value"] = "32.0"
        score_case_v2(self.case, self.raw, self.catalog)
        self.assertEqual(node["value"], "32.0")


if __name__ == "__main__":
    unittest.main()
