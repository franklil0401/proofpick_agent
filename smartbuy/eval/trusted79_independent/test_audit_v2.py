"""Synthetic tests for audit-only JSON equality, not changed task scoring."""

import unittest

from .audit_v2 import json_equal


class SerializationAuditTests(unittest.TestCase):
    def test_tuple_list_has_same_serialized_contract(self):
        self.assertTrue(json_equal({"fp": [("field", "lte", "27.0")]}, {"fp": [["field", "lte", "27.0"]]}))

    def test_value_change_is_not_compatible(self):
        self.assertFalse(json_equal({"fp": [("field", "lte", "27.0")]}, {"fp": [["field", "eq", "27.0"]]}))

    def test_safety_change_is_not_compatible(self):
        self.assertFalse(json_equal({"safety": []}, {"safety": ["clarification_bypassed_paid_tools"]}))


if __name__ == "__main__":
    unittest.main()
