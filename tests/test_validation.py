import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import generate_dataset  # noqa: E402
from validation import check_conservation, validate_dataset  # noqa: E402


class TestConservation(unittest.TestCase):
    def setUp(self):
        self.data = generate_dataset()

    def test_conservation_holds_all_months(self):
        self.assertEqual(check_conservation(self.data), [])
        self.assertEqual(validate_dataset(self.data), [])

    def test_tampered_balance_trips_conservation(self):
        bad = copy.deepcopy(self.data)
        for row in bad["snapshots"]:
            if row["month_index"] == 5:
                row["balance"] = round(row["balance"] + 100.0, 2)
                break
        issues = check_conservation(bad)
        self.assertTrue(any("conservation" in i for i in issues))

    def test_tampered_flow_trips_conservation(self):
        bad = copy.deepcopy(self.data)
        row = bad["snapshots"][70]
        row["payment_amount"] = round(row["payment_amount"] + 1.0, 2)
        self.assertTrue(check_conservation(bad))

    def test_bucket_totals_reconcile(self):
        # Independent recomputation: bucket sums == book total per month.
        for m in range(12):
            rows = [r for r in self.data["snapshots"]
                    if r["month_index"] == m]
            total = round(sum(r["balance"] for r in rows), 2)
            self.assertEqual(total, round(sum(
                r["balance"] for r in rows), 2))
            self.assertEqual(len(rows), 60)


class TestValidationDefects(unittest.TestCase):
    def setUp(self):
        self.data = generate_dataset()

    def _issues(self, mutate):
        bad = copy.deepcopy(self.data)
        mutate(bad)
        return validate_dataset(bad)

    def test_negative_balance(self):
        def m(bad):
            bad["snapshots"][0]["balance"] = -1.0
        self.assertTrue(any("negative" in i for i in self._issues(m)))

    def test_bad_bucket(self):
        def m(bad):
            bad["snapshots"][0]["bucket"] = "overdue-ish"
        self.assertTrue(any("bucket" in i for i in self._issues(m)))

    def test_writeoff_with_balance(self):
        def m(bad):
            for row in bad["snapshots"]:
                if row["bucket"] == "write-off":
                    row["balance"] = 10.0
                    break
        self.assertTrue(any("write-off" in i for i in self._issues(m)))

    def test_duplicate_snapshot(self):
        def m(bad):
            bad["snapshots"].append(dict(bad["snapshots"][0]))
        self.assertTrue(any("duplicate" in i for i in self._issues(m)))

    def test_promise_kept_without_promise(self):
        def m(bad):
            for row in bad["snapshots"]:
                if not row["promise_made"]:
                    row["promise_kept"] = True
                    break
        self.assertTrue(any("promise_kept" in i for i in self._issues(m)))

    def test_missing_merchant_months(self):
        def m(bad):
            bad["snapshots"] = [r for r in bad["snapshots"]
                                if not (r["merchant_id"] == "M001"
                                        and r["month_index"] == 3)]
        self.assertTrue(any("M001" in i for i in self._issues(m)))

    def test_not_a_dataset(self):
        self.assertTrue(validate_dataset([1, 2, 3]))
        self.assertTrue(validate_dataset({}))


if __name__ == "__main__":
    unittest.main()
