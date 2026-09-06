"""Synthetic checks only; no original query execution or providers."""

import unittest

from .metrics import metrics


class MetricsTests(unittest.TestCase):
    def test_empty_is_not_pass(self):
        result = metrics([], [])
        self.assertEqual(result["planned"], 15)
        self.assertEqual(result["remaining_in_phase"], 15)
        self.assertIsNone(result["f1"])
        self.assertFalse(result["exposed15_regression_passed"])
        self.assertNotIn("trusted79_gate_passed", result)

    def test_executed_unscored_is_not_success(self):
        result = metrics([], [{"usage": [], "latency_ms": 10}])
        self.assertEqual(result["executed"], 1)
        self.assertEqual(result["scored"], 0)
        self.assertEqual(result["remaining_in_phase"], 14)
        self.assertFalse(result["exposed15_regression_passed"])


if __name__ == "__main__":
    unittest.main()
