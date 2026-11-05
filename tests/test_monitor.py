import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generator import generate_dataset  # noqa: E402
from helpers import make_dataset, snap  # noqa: E402
from monitor import (bucket_summary, cure_rates, promises_summary,  # noqa: E402
                     roll_matrix)


class TestBucketSummary(unittest.TestCase):
    def test_full_book(self):
        data = generate_dataset()
        summary = bucket_summary(data)
        self.assertEqual(len(summary), 12)
        for month in summary:
            self.assertEqual(month["total_count"], 60)
            self.assertEqual(
                sum(b["count"] for b in month["buckets"].values()), 60)
            self.assertAlmostEqual(
                sum(b["balance"] for b in month["buckets"].values()),
                month["total_balance"], places=2)

    def test_latest_month_pinned(self):
        last = bucket_summary(generate_dataset())[-1]
        self.assertEqual(last["buckets"]["current"]["count"], 34)
        self.assertEqual(last["buckets"]["write-off"]["count"], 10)
        self.assertEqual(last["total_balance"], 1203450.19)


class TestRollMatrixHandComputed(unittest.TestCase):
    """Two merchants, three real transitions each, padded after.

    A: current -> 1-30 -> 31-60 (balances 100, 110, 120)
    B: 1-30 -> current -> current (balances 200, 180, 180)
    """

    def setUp(self):
        self.data = make_dataset({
            "A": [snap("A", 0, "current", 100.0),
                  snap("A", 1, "1-30", 110.0, charges=10.0),
                  snap("A", 2, "31-60", 120.0, charges=10.0)],
            "B": [snap("B", 0, "1-30", 200.0),
                  snap("B", 1, "current", 180.0, payments=20.0),
                  snap("B", 2, "current", 180.0)],
        })
        self.roll = roll_matrix(self.data)

    def test_counts(self):
        counts = self.roll["counts"]
        self.assertEqual(counts["current"]["1-30"], 1)
        self.assertEqual(counts["1-30"]["31-60"], 1)
        self.assertEqual(counts["1-30"]["current"], 1)
        # Padded months: A stays 31-60 (9), B stays current (9 + 1 real)
        self.assertEqual(counts["31-60"]["31-60"], 9)
        self.assertEqual(counts["current"]["current"], 10)
        total = sum(sum(r.values()) for r in counts.values())
        self.assertEqual(total, 22)  # 2 merchants x 11 transitions

    def test_balance_weights_use_from_month_balance(self):
        balances = self.roll["balances"]
        self.assertEqual(balances["current"]["1-30"], 100.0)
        self.assertEqual(balances["1-30"]["current"], 200.0)
        self.assertEqual(balances["1-30"]["31-60"], 110.0)

    def test_rates_rows_sum_to_100(self):
        for table in (self.roll["count_rates"], self.roll["balance_rates"]):
            for bucket, row in table.items():
                total = sum(row.values())
                if any(v for v in
                       self.roll["counts"][bucket].values()):
                    self.assertAlmostEqual(total, 100.0, places=3)


class TestCureAndPromisesHandComputed(unittest.TestCase):
    def setUp(self):
        # A delinquent then cures; B delinquent then stays delinquent.
        self.data = make_dataset({
            "A": [snap("A", 0, "1-30", 100.0, made=True, kept=True,
                       promised=50.0),
                  snap("A", 1, "current", 80.0, payments=20.0)],
            "B": [snap("B", 0, "31-60", 200.0, made=True, kept=False,
                       promised=80.0),
                  snap("B", 1, "1-30", 190.0, payments=10.0)],
        })

    def test_cure_rate_first_transition(self):
        cures = cure_rates(self.data)
        first = cures["per_transition"][0]
        self.assertEqual((first["delinquent"], first["cured"]), (2, 1))
        self.assertEqual(first["cure_rate"], 0.5)

    def test_promises_first_month(self):
        promises = promises_summary(self.data)
        first = promises["per_month"][0]
        self.assertEqual((first["made"], first["kept"], first["broken"]),
                         (2, 1, 1))
        self.assertEqual(first["kept_rate"], 0.5)
        self.assertEqual(first["promised_amount"], 130.0)

    def test_full_book_pinned_totals(self):
        data = generate_dataset()
        promises = promises_summary(data)
        self.assertEqual((promises["made"], promises["kept"]), (161, 79))
        self.assertEqual(promises["kept_rate"], 0.4907)
        cures = cure_rates(data)
        self.assertEqual((cures["cured"], cures["delinquent"]), (56, 216))
        self.assertEqual(cures["cure_rate"], 0.2593)


if __name__ == "__main__":
    unittest.main()
