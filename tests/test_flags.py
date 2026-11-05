import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flags import backtest_flags, compute_flags  # noqa: E402
from generator import generate_dataset  # noqa: E402
from helpers import make_dataset, snap  # noqa: E402


class TestFlagRulesHandComputed(unittest.TestCase):
    def test_two_consecutive_worsening(self):
        data = make_dataset({"A": [
            snap("A", 0, "current", 100.0),
            snap("A", 1, "1-30", 110.0, charges=10.0),
            snap("A", 2, "31-60", 120.0, charges=10.0),
            snap("A", 3, "current", 60.0, payments=60.0)]})
        flags = compute_flags(data)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["month_index"], 2)
        self.assertIn("two_consecutive_worsening", flags[0]["reasons"])

    def test_single_worsening_does_not_flag(self):
        data = make_dataset({"A": [
            snap("A", 0, "current", 100.0),
            snap("A", 1, "1-30", 110.0, charges=10.0),
            snap("A", 2, "current", 90.0, payments=20.0)]})
        self.assertEqual(compute_flags(data), [])

    def test_broken_promise_with_growth(self):
        data = make_dataset({"A": [
            snap("A", 0, "1-30", 100.0),
            snap("A", 1, "31-60", 120.0, charges=20.0,
                 made=True, kept=False, promised=30.0)]})
        flags = compute_flags(data)
        self.assertEqual(len(flags), 1)
        self.assertIn("broken_promise_with_growth", flags[0]["reasons"])

    def test_broken_promise_without_growth_does_not_flag(self):
        data = make_dataset({"A": [
            snap("A", 0, "1-30", 100.0),
            snap("A", 1, "31-60", 90.0, payments=10.0,
                 made=True, kept=False, promised=30.0)]})
        self.assertEqual(compute_flags(data), [])

    def test_broken_promise_at_1_30_does_not_flag_r2(self):
        # R2 requires at least 31-60; shallow delinquency alone is noise.
        data = make_dataset({"A": [
            snap("A", 0, "current", 100.0),
            snap("A", 1, "1-30", 120.0, charges=20.0,
                 made=True, kept=False, promised=30.0)]})
        self.assertEqual(compute_flags(data), [])


class TestBacktestOnPlantedBook(unittest.TestCase):
    def setUp(self):
        self.data = generate_dataset()
        self.bt = backtest_flags(self.data)
        self.flags = compute_flags(self.data)
        self.arch = {m["merchant_id"]: m["archetype"]
                     for m in self.data["merchants"]}

    def test_headline_numbers_pinned(self):
        self.assertEqual(self.bt["precision"], 0.625)
        self.assertEqual(self.bt["recall"], 1.0)
        self.assertEqual(self.bt["flags_evaluated"], 16)
        self.assertEqual(self.bt["true_positive_flags"], 10)
        self.assertEqual(self.bt["false_positive_flags"], 6)
        self.assertEqual(self.bt["rollers"], 10)

    def test_every_deteriorator_flagged(self):
        flagged = {f["merchant_id"] for f in self.flags}
        for mid, a in self.arch.items():
            if a == "deteriorating":
                self.assertIn(mid, flagged)

    def test_no_stable_or_curing_flagged(self):
        flagged = {f["merchant_id"] for f in self.flags}
        for mid, a in self.arch.items():
            if a in ("stable_current", "stable_delinquent", "curing",
                     "cyclical"):
                self.assertNotIn(mid, flagged)

    def test_false_positives_are_the_planted_stressed(self):
        evaluated_fp = {mid for mid, a in self.arch.items()
                        if a == "stressed_recovering"}
        flagged = {f["merchant_id"] for f in self.flags}
        self.assertTrue(evaluated_fp <= flagged)


if __name__ == "__main__":
    unittest.main()
