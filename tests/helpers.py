"""Shared builders for the test suite (not a test module).

Hand-built tiny books where roll rates, cure rates, promise rates
and flag outcomes can be verified by hand.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import month_label  # noqa: E402


def snap(mid, m, bucket, balance, charges=0.0, payments=0.0,
         write_off=0.0, made=False, kept=None, promised=0.0):
    return {"merchant_id": mid, "merchant_name": f"Test {mid}",
            "month_index": m, "month": month_label(m), "bucket": bucket,
            "balance": balance, "charge_amount": charges,
            "payment_amount": payments, "write_off_amount": write_off,
            "promise_made": made, "promise_kept": kept,
            "promised_amount": promised}


def make_dataset(merchant_paths):
    """merchant_paths: {merchant_id: [snapshot rows in month order]}.

    Months beyond each path's length are padded with the last bucket
    at the same balance (zero flows) so every merchant has 12 rows.
    """
    merchants, snapshots = [], []
    for mid, rows in sorted(merchant_paths.items()):
        merchants.append({"merchant_id": mid,
                          "merchant_name": f"Test {mid}",
                          "archetype": "test"})
        padded = list(rows)
        last = rows[-1]
        for m in range(len(rows), 12):
            padded.append(snap(mid, m, last["bucket"], last["balance"]))
        snapshots.extend(padded)
    labels = [month_label(m) for m in range(12)]
    return {"seed": 0, "months": 12, "month_labels": labels,
            "buckets": ["current", "1-30", "31-60", "61-90", "90+",
                        "write-off"],
            "merchants": merchants, "snapshots": snapshots}
