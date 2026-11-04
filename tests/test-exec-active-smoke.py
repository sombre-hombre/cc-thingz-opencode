#!/usr/bin/env python3
"""Negative checks for real-smoke evidence validation, without model requests."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("active_smoke", Path(__file__).parent / "smoke/exec-task-loop-active.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class EvidenceValidation(unittest.TestCase):
    def setUp(self):
        self.calls = [{"name": "subagent", "state": {"status": "completed", "input": {
            "agent": "general", "prompt": "/fixture/work /fixture/plan"}},
            "time": {"ran": start, "completed": start + 10}} for start in (10, 30)]

    def check(self, calls):
        return smoke.validate_calls(calls, "/fixture/work", "/fixture/plan")

    def test_ordered(self):
        self.assertEqual(len(self.check(self.calls)), 2)

    def test_overlap(self):
        self.calls[1]["time"]["ran"] = 19
        with self.assertRaisesRegex(AssertionError, "parallel"):
            self.check(self.calls)

    def test_missing_child(self):
        with self.assertRaisesRegex(AssertionError, "exactly two"):
            self.check(self.calls[:1])

    def test_failed_child(self):
        self.calls[0]["state"]["status"] = "error"
        with self.assertRaises(AssertionError):
            self.check(self.calls)

    def test_fresh_foreground_context(self):
        for key, value in (("sessionID", "ses_existing"), ("background", True),
                           ("agent", "build"), ("prompt", "missing absolute paths")):
            with self.subTest(key=key):
                calls = copy.deepcopy(self.calls)
                calls[0]["state"]["input"][key] = value
                with self.assertRaises(AssertionError):
                    self.check(calls)


if __name__ == "__main__":
    unittest.main()
