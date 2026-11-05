"""Rules-based early-risk flags + their backtest.

No scoring model (by design — see README scope). Two explicit,
auditable rules; a merchant-month is flagged when either fires:

  R1 two-consecutive-worsening — the bucket order rose in each of
     the last two monthly transitions (e.g. current -> 1-30 ->
     31-60). Needs month_index >= 2.
  R2 broken-promise-with-growth — the merchant is at least 31-60,
     broke a promise-to-pay this month, AND the balance grew versus
     last month. Needs month_index >= 1.

**backtest** — flags are graded against what happened next:
  * an evaluated flag is one raised while the merchant was still
    below 60+ (bucket order < 3) with a full two-month follow-up
    window inside the book (month_index <= 9);
  * **precision** — of those evaluated flags, the share whose
    merchant actually reached 60+ (61-90 / 90+ / write-off) within
    the next two months;
  * **recall** — of the merchants who ever reached 60+, the share
    who carried a flag in the two months before first reaching it.
"""

from __future__ import annotations

from typing import Dict, List

from generator import BUCKET_ORDER, MONTHS

SIXTY_PLUS_ORDER = BUCKET_ORDER["61-90"]  # 3


def _by_merchant(dataset: Dict) -> Dict[str, List[Dict]]:
    out: Dict[str, List[Dict]] = {}
    for r in dataset["snapshots"]:
        out.setdefault(r["merchant_id"], []).append(r)
    for rows in out.values():
        rows.sort(key=lambda r: r["month_index"])
    return out


def compute_flags(dataset: Dict) -> List[Dict]:
    """All flag instances, sorted by (month_index, merchant_id)."""
    names = {m["merchant_id"]: m["merchant_name"]
             for m in dataset.get("merchants", [])}
    flags: List[Dict] = []
    for mid, rows in sorted(_by_merchant(dataset).items()):
        for i, row in enumerate(rows):
            reasons = []
            if i >= 2:
                o = [BUCKET_ORDER[r["bucket"]] for r in rows]
                if o[i] > o[i - 1] and o[i - 1] > o[i - 2]:
                    reasons.append("two_consecutive_worsening")
            if i >= 1:
                prev = rows[i - 1]
                if BUCKET_ORDER[row["bucket"]] >= BUCKET_ORDER["31-60"] \
                        and row["promise_made"] \
                        and row["promise_kept"] is False \
                        and row["balance"] > prev["balance"]:
                    reasons.append("broken_promise_with_growth")
            if reasons:
                flags.append({
                    "merchant_id": mid,
                    "merchant_name": names.get(mid, mid),
                    "month_index": row["month_index"],
                    "month": row["month"],
                    "bucket": row["bucket"],
                    "balance": row["balance"],
                    "reasons": reasons,
                })
    return sorted(flags, key=lambda f: (f["month_index"], f["merchant_id"]))


def _first_sixty_plus(rows: List[Dict]):
    for r in rows:
        if BUCKET_ORDER[r["bucket"]] >= SIXTY_PLUS_ORDER:
            return r["month_index"]
    return None


def backtest_flags(dataset: Dict) -> Dict:
    flags = compute_flags(dataset)
    by_merchant = _by_merchant(dataset)
    order_at = {(mid, r["month_index"]): BUCKET_ORDER[r["bucket"]]
                for mid, rows in by_merchant.items() for r in rows}

    evaluated = tp = 0
    for f in flags:
        t, mid = f["month_index"], f["merchant_id"]
        if t > MONTHS - 3:               # need months t+1 and t+2
            continue
        if order_at[(mid, t)] >= SIXTY_PLUS_ORDER:
            continue                     # early warning means BEFORE 60+
        evaluated += 1
        if any(order_at.get((mid, t + d), -1) >= SIXTY_PLUS_ORDER
               for d in (1, 2)):
            tp += 1
    rollers, flagged_rollers = [], []
    flag_months: Dict[str, List[int]] = {}
    for f in flags:
        flag_months.setdefault(f["merchant_id"], []).append(f["month_index"])
    for mid, rows in sorted(by_merchant.items()):
        first = _first_sixty_plus(rows)
        if first is None or first == 0:
            continue
        rollers.append(mid)
        if any(first - 2 <= t < first for t in flag_months.get(mid, [])):
            flagged_rollers.append(mid)
    precision = round(tp / evaluated, 4) if evaluated else 0.0
    recall = round(len(flagged_rollers) / len(rollers), 4) if rollers else 0.0
    return {
        "flags_total": len(flags),
        "flags_evaluated": evaluated,
        "true_positive_flags": tp,
        "false_positive_flags": evaluated - tp,
        "precision": precision,
        "rollers": len(rollers),
        "rollers_flagged_before": len(flagged_rollers),
        "recall": recall,
        "roller_merchant_ids": rollers,
        "flagged_roller_merchant_ids": flagged_rollers,
    }
