"""Deterministic synthetic merchant arrears book — fictional merchants.

SYNTHETIC DATA ONLY. No real company, merchant, or loan data is ever
used. Every row is fabricated from a seeded PRNG so the same seed
always yields the same book, byte-for-byte.

One snapshot row per merchant per month, 12 months, 60 merchants:

  merchant_id, merchant_name, month_index, month, bucket, balance,
  charge_amount, payment_amount, write_off_amount,
  promise_made, promise_kept, promised_amount

Buckets (delinquency stages, in worsening order):
  current, 1-30, 31-60, 61-90, 90+, write-off

Planted archetypes (pinned by tests and golden evals):
  * stable_current (18)      — current every month;
  * stable_delinquent (8)    — parked in 1-30 every month;
  * deteriorating (10)       — worsens one bucket a month from a
                               staggered start until 90+/write-off;
  * curing (10)              — starts at 61-90 and steps back to
                               current, then stays current;
  * cyclical (8)             — bounces current <-> 1-30, never two
                               worsening months in a row;
  * stressed_recovering (6)  — worsens twice (to 31-60), then cures
                               back to current: the planted
                               false-alarm pattern for the flag
                               backtest.

Balance flows are generated first (charges / payments / write-off)
and each balance is DERIVED as
  balance = prev_balance + charges - payments - write_off_amount
(round to the cent), so balance conservation holds exactly by
construction and is then re-asserted independently by validation,
tests, and evals.
"""

from __future__ import annotations

import random
from typing import Dict, List

DEFAULT_SEED = 42
MONTHS = 12
START_YEAR, START_MONTH = 2025, 1

BUCKETS = ["current", "1-30", "31-60", "61-90", "90+", "write-off"]
BUCKET_ORDER = {b: i for i, b in enumerate(BUCKETS)}
DELINQUENT = ["1-30", "31-60", "61-90", "90+"]

SNAPSHOT_FIELDS = ["merchant_id", "merchant_name", "month_index",
                   "month", "bucket", "balance", "charge_amount",
                   "payment_amount", "write_off_amount",
                   "promise_made", "promise_kept", "promised_amount"]

_NAME_A = ["Northwind", "BluePeak", "Harborline", "CedarPoint",
           "SilverOak", "RedMesa", "GoldenGate", "IronBridge",
           "PalmCourt", "StoneField", "ClearWater", "HighPlains"]
_NAME_B = ["Logistics", "Retail Group", "Foods", "Auto Parts",
           "Hospitality", "Apparel", "Electronics", "Furniture",
           "Pharmacy", "Hardware", "Fitness", "Pet Supplies"]


def month_label(month_index: int) -> str:
    y = START_YEAR + (START_MONTH - 1 + month_index) // 12
    m = (START_MONTH - 1 + month_index) % 12 + 1
    return f"{y:04d}-{m:02d}"


def merchant_name(i: int) -> str:
    return f"{_NAME_A[i % len(_NAME_A)]} {_NAME_B[(i // len(_NAME_A)) % len(_NAME_B)]} {i + 1:02d}"


def archetype_of(index: int) -> str:
    if index < 18:
        return "stable_current"
    if index < 26:
        return "stable_delinquent"
    if index < 36:
        return "deteriorating"
    if index < 46:
        return "curing"
    if index < 54:
        return "cyclical"
    return "stressed_recovering"


def trajectory(archetype: str, index: int) -> List[str]:
    """The 12-month bucket path planted for one merchant."""
    if archetype == "stable_current":
        return ["current"] * MONTHS
    if archetype == "stable_delinquent":
        return ["1-30"] * MONTHS
    if archetype == "deteriorating":
        start = 1 + (index % 4)          # first worsening month: 1..4
        path = []
        order = 0
        for m in range(MONTHS):
            if m >= start:
                order = min(order + 1, 5)
            path.append(BUCKETS[order])
            if order == 5:
                pass                     # write-off is absorbing
        return path
    if archetype == "curing":
        start_order = 3                  # 61-90
        return [BUCKETS[max(start_order - m, 0)] for m in range(MONTHS)]
    if archetype == "cyclical":
        return ["1-30" if m % 2 == 1 else "current" for m in range(MONTHS)]
    if archetype == "stressed_recovering":
        start = 2 + (index % 3)          # first worsening month: 2..4
        path = []
        for m in range(MONTHS):
            if m < start:
                path.append("current")
            elif m == start:
                path.append("1-30")
            elif m == start + 1:
                path.append("31-60")
            elif m == start + 2:
                path.append("1-30")
            else:
                path.append("current")
        return path
    raise ValueError(f"unknown archetype: {archetype}")


def _flows(rng: random.Random, prev_bucket: str, bucket: str,
           prev_balance: float):
    """Return (charges, payments, write_off, balance) for one month.

    Month-0 rows are handled by the caller (all flows zero).
    The balance is derived from the flows, never chosen separately.
    """
    prev_o, o = BUCKET_ORDER[prev_bucket], BUCKET_ORDER[bucket]
    if bucket == "write-off":
        charges = round(prev_balance * rng.uniform(0.0, 0.02), 2)
        payments = round(prev_balance * rng.uniform(0.0, 0.02), 2)
        write_off = round(prev_balance + charges - payments, 2)
        return charges, payments, write_off, 0.0
    if prev_balance <= 0:
        return 0.0, 0.0, 0.0, 0.0
    if o > prev_o:                       # worsening: charges dominate
        payments = round(prev_balance * rng.uniform(0.0, 0.03), 2)
        charges = round(prev_balance * rng.uniform(0.08, 0.15), 2)
    elif o < prev_o:                     # improving: payments dominate
        charges = round(prev_balance * rng.uniform(0.0, 0.03), 2)
        payments = round(prev_balance * rng.uniform(0.10, 0.20), 2)
    elif bucket == "current":            # steady current: both sides
        charges = round(prev_balance * rng.uniform(0.05, 0.10), 2)
        payments = round(prev_balance * rng.uniform(0.05, 0.10), 2)
    else:                                # steady delinquent: near-flat
        charges = round(prev_balance * rng.uniform(0.03, 0.06), 2)
        payments = round(prev_balance * rng.uniform(0.03, 0.06), 2)
    balance = round(prev_balance + charges - payments, 2)
    if balance <= 0:
        balance = round(prev_balance * 0.5, 2)
        payments = round(prev_balance + charges - balance, 2)
    return charges, payments, 0.0, balance


def _promise(rng: random.Random, archetype: str, bucket: str,
             balance: float):
    """Return (made, kept, promised_amount) for one snapshot row."""
    if bucket not in DELINQUENT:
        return False, None, 0.0
    if archetype == "deteriorating":
        made, kept_p = True, 0.20
    elif archetype == "curing":
        made, kept_p = True, 0.85
    elif archetype == "stable_delinquent":
        made, kept_p = rng.random() < 0.5, 0.50
    elif archetype == "stressed_recovering":
        made, kept_p = True, 0.25
    else:                                # cyclical
        made, kept_p = rng.random() < 0.6, 0.70
    if not made:
        return False, None, 0.0
    kept = rng.random() < kept_p
    amount = round(balance * rng.uniform(0.10, 0.30), 2)
    return True, kept, amount


def generate_dataset(seed: int = DEFAULT_SEED,
                     merchants: int = 60) -> Dict:
    """Return the full synthetic book, deterministic for ``seed``."""
    if merchants < 1 or merchants > 60:
        raise ValueError("merchants must be between 1 and 60 "
                         "(archetype blocks are defined for 60)")
    rng = random.Random(seed)
    merchant_rows, snapshots = [], []
    for i in range(merchants):
        mid = f"M{i + 1:03d}"
        name = merchant_name(i)
        arch = archetype_of(i)
        merchant_rows.append({"merchant_id": mid, "merchant_name": name,
                              "archetype": arch})
        path = trajectory(arch, i)
        balance = round(rng.uniform(5000.0, 50000.0), 2)
        for m in range(MONTHS):
            bucket = path[m]
            if m == 0:
                charges = payments = write_off = 0.0
                if bucket == "write-off":
                    balance = 0.0
            else:
                charges, payments, write_off, balance = _flows(
                    rng, path[m - 1], bucket, balance)
            made, kept, promised = _promise(rng, arch, bucket, balance)
            snapshots.append({
                "merchant_id": mid, "merchant_name": name,
                "month_index": m, "month": month_label(m),
                "bucket": bucket, "balance": balance,
                "charge_amount": charges, "payment_amount": payments,
                "write_off_amount": write_off,
                "promise_made": made, "promise_kept": kept,
                "promised_amount": promised,
            })
    return {"seed": seed, "months": MONTHS,
            "month_labels": [month_label(m) for m in range(MONTHS)],
            "buckets": list(BUCKETS), "merchants": merchant_rows,
            "snapshots": snapshots}


def snapshots_of(dataset: Dict) -> List[Dict]:
    return list(dataset["snapshots"])


def dataset_to_json(dataset: Dict) -> str:
    import json
    return json.dumps(dataset, sort_keys=True) + "\n"
