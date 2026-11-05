import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import (BUCKETS, archetype_of, generate_dataset,  # noqa: E402
                       month_label, trajectory)


class TestGenerator(unittest.TestCase):
    def setUp(self):
        self.data = generate_dataset()

    def test_shape(self):
        self.assertEqual(len(self.data["merchants"]), 60)
        self.assertEqual(len(self.data["snapshots"]), 720)
        self.assertEqual(self.data["month_labels"][0], "2025-01")
        self.assertEqual(self.data["month_labels"][-1], "2025-12")
        per = {}
        for r in self.data["snapshots"]:
            per[r["merchant_id"]] = per.get(r["merchant_id"], 0) + 1
        self.assertTrue(all(v == 12 for v in per.values()))

    def test_determinism(self):
        self.assertEqual(generate_dataset(), generate_dataset())
        self.assertNotEqual(generate_dataset(seed=7), self.data)

    def test_buckets_valid_and_writeoff_zero(self):
        for r in self.data["snapshots"]:
            self.assertIn(r["bucket"], BUCKETS)
            if r["bucket"] == "write-off":
                self.assertEqual(r["balance"], 0.0)
            else:
                self.assertGreater(r["balance"], 0)

    def test_archetype_blocks(self):
        counts = {}
        for m in self.data["merchants"]:
            counts[m["archetype"]] = counts.get(m["archetype"], 0) + 1
        self.assertEqual(counts, {"stable_current": 18,
                                  "stable_delinquent": 8,
                                  "deteriorating": 10, "curing": 10,
                                  "cyclical": 8,
                                  "stressed_recovering": 6})

    def test_trajectories(self):
        self.assertEqual(trajectory("stable_current", 0), ["current"] * 12)
        det = trajectory("deteriorating", 26)  # start = 1 + 26%4 = 3
        self.assertEqual(det[:4], ["current", "current", "current", "1-30"])
        self.assertEqual(det[5], "61-90")
        self.assertEqual(det[6], "90+")
        self.assertEqual(det[-1], "write-off")
        cur = trajectory("curing", 36)
        self.assertEqual(cur[:4], ["61-90", "31-60", "1-30", "current"])
        self.assertEqual(cur[-1], "current")
        stressed = trajectory("stressed_recovering", 54)  # start=2
        self.assertEqual(stressed[2:6], ["1-30", "31-60", "1-30", "current"])

    def test_month_label_rollover(self):
        self.assertEqual(month_label(0), "2025-01")
        self.assertEqual(month_label(11), "2025-12")

    def test_merchant_count_guard(self):
        with self.assertRaises(ValueError):
            generate_dataset(merchants=61)
        with self.assertRaises(ValueError):
            archetype_of(0) and generate_dataset(merchants=0)

    def test_names_unique(self):
        names = [m["merchant_name"] for m in self.data["merchants"]]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
