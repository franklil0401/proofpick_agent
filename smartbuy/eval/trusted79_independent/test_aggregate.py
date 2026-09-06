"""Synthetic denominator checks; no frozen task inputs or model calls."""

import unittest

from .aggregate import aggregate


class AggregationTests(unittest.TestCase):
    def test_unrun_is_not_failure_or_pass(self):
        result = aggregate([], [])
        self.assertEqual((result["executed"], result["remaining"]), (0, 79))
        self.assertIsNone(result["f1"])
        self.assertEqual(result["recommendation_fact_evidence"], [0, 0])
        self.assertFalse(result["trusted79_gate_passed"])
        self.assertNotIn("release_gate_passed", result)

    def test_raw_without_score_stays_executed(self):
        result = aggregate([], [{"usage": [], "latency_ms": 10}])
        self.assertEqual((result["executed"], result["scored"], result["remaining"]), (1, 0, 78))
        self.assertFalse(result["trusted79_gate_passed"])


if __name__ == "__main__":
    unittest.main()
