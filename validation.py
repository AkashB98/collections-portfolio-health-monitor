"""Data-quality gate + balance-conservation check.

Reports issues, never raises on bad data, so the CLI ``check`` gate
maps data problems to exit code 2, distinctly from a flag-quality
breach (exit 1).

**balance conservation** — every dollar is accounted for: for each
merchant and each month after the first,
  balance == prev_balance + charges - payments - write_off_amount
to the cent, and the per-bucket balances sum to the book total.
"""

from __future__ import annotations

from typing import Dict, List

from generator import BUCKETS, BUCKET_ORDER, MONTHS, SNAPSHOT_FIELDS

TOL = 0.005  # half a cent


def check_conservation(dataset: Dict) -> List[str]:
    """Return conservation violations (empty list = holds exactly)."""
    issues: List[str] = []
    by_merchant: Dict[str, List[Dict]] = {}
    for row in dataset.get("snapshots", []):
        by_merchant.setdefault(row.get("merchant_id"), []).append(row)
    for mid, rows in sorted(by_merchant.items()):
        rows = sorted(rows, key=lambda r: r.get("month_index", -1))
        for prev, cur in zip(rows, rows[1:]):
            expected = round(prev["balance"] + cur["charge_amount"]
                             - cur["payment_amount"]
                             - cur["write_off_amount"], 2)
            if abs(expected - cur["balance"]) > TOL:
                issues.append(
                    f"conservation: {mid} month {cur.get('month_index')}: "
                    f"balance {cur['balance']} != prev {prev['balance']} "
                    f"+ charges {cur['charge_amount']} - payments "
                    f"{cur['payment_amount']} - write-off "
                    f"{cur['write_off_amount']} (= {expected})")
    # Bucket totals must sum to the book total, every month.
    for m in range(MONTHS):
        rows = [r for r in dataset.get("snapshots", [])
                if r.get("month_index") == m]
        if not rows:
            continue
        total = round(sum(r["balance"] for r in rows), 2)
        per_bucket = round(sum(
            round(sum(r["balance"] for r in rows
                      if r["bucket"] == b), 2) for b in BUCKETS), 2)
        if abs(total - per_bucket) > TOL:
            issues.append(f"conservation: month {m} bucket totals "
                          f"{per_bucket} != book total {total}")
    return issues


def validate_dataset(dataset: Dict) -> List[str]:
    issues: List[str] = []
    if not isinstance(dataset, dict):
        return ["dataset must be a JSON object"]
    snapshots = dataset.get("snapshots")
    if not isinstance(snapshots, list) or not snapshots:
        return ["dataset.snapshots missing or empty"]
    merchants = dataset.get("merchants")
    if not isinstance(merchants, list) or not merchants:
        issues.append("dataset.merchants missing or empty")
        merchants = []
    known = {m.get("merchant_id") for m in merchants
             if isinstance(m, dict)}
    seen = set()
    for row in snapshots:
        if not isinstance(row, dict):
            issues.append("snapshot row is not an object")
            continue
        for field in SNAPSHOT_FIELDS:
            if field not in row:
                issues.append(f"missing field {field} in row {row!r:.80}")
        mid, mi = row.get("merchant_id"), row.get("month_index")
        if known and mid not in known:
            issues.append(f"unknown merchant_id: {mid}")
        key = (mid, mi)
        if key in seen:
            issues.append(f"duplicate snapshot: {mid} month {mi}")
        seen.add(key)
        if not isinstance(mi, int) or isinstance(mi, bool) \
                or not (0 <= mi < MONTHS):
            issues.append(f"bad month_index for {mid}: {mi!r}")
        if row.get("bucket") not in BUCKET_ORDER:
            issues.append(f"bad bucket for {mid} month {mi}: "
                          f"{row.get('bucket')!r}")
        bal = row.get("balance")
        if not isinstance(bal, (int, float)) or isinstance(bal, bool):
            issues.append(f"balance not a number for {mid} month {mi}")
        elif bal < -TOL:
            issues.append(f"negative balance for {mid} month {mi}: {bal}")
        elif row.get("bucket") == "write-off" and abs(bal) > TOL:
            issues.append(f"write-off balance must be 0 for {mid} "
                          f"month {mi}: {bal}")
        for f in ("charge_amount", "payment_amount",
                  "write_off_amount", "promised_amount"):
            v = row.get(f)
            if not isinstance(v, (int, float)) or isinstance(v, bool) \
                    or v < -TOL:
                issues.append(f"bad {f} for {mid} month {mi}: {v!r}")
        if row.get("promise_made") is True \
                and row.get("promise_kept") not in (True, False):
            issues.append(f"promise_kept must be true/false when a "
                          f"promise was made ({mid} month {mi})")
        if row.get("promise_made") is False \
                and row.get("promise_kept") is not None:
            issues.append(f"promise_kept must be null when no promise "
                          f"was made ({mid} month {mi})")
    for m in merchants:
        rows = [r for r in snapshots
                if r.get("merchant_id") == m.get("merchant_id")]
        if len(rows) != MONTHS:
            issues.append(f"merchant {m.get('merchant_id')} has "
                          f"{len(rows)} snapshots, expected {MONTHS}")
    issues.extend(check_conservation(dataset))
    return issues
