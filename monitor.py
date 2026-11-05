"""Live-book monitoring: bucket summary, roll rates, promises, cures.

**roll rate** — the share of a delinquency bucket that moves to
another bucket next month; the core health signal of a live book.
**cure rate** — the share of delinquent accounts that return to
current next month.
"""

from __future__ import annotations

from typing import Dict, List

from generator import BUCKETS, BUCKET_ORDER, DELINQUENT, MONTHS


def _rows_by_month(dataset: Dict) -> Dict[int, List[Dict]]:
    out: Dict[int, List[Dict]] = {}
    for r in dataset["snapshots"]:
        out.setdefault(r["month_index"], []).append(r)
    return out


def _paired(dataset: Dict):
    """Yield (prev_row, cur_row) pairs per merchant, month order."""
    by_merchant: Dict[str, List[Dict]] = {}
    for r in dataset["snapshots"]:
        by_merchant.setdefault(r["merchant_id"], []).append(r)
    for mid in sorted(by_merchant):
        rows = sorted(by_merchant[mid], key=lambda r: r["month_index"])
        for prev, cur in zip(rows, rows[1:]):
            yield prev, cur


def bucket_summary(dataset: Dict) -> List[Dict]:
    """Per month: count and balance in every bucket + book total."""
    by_month = _rows_by_month(dataset)
    labels = dataset.get("month_labels") or []
    out = []
    for m in range(MONTHS):
        rows = by_month.get(m, [])
        buckets = {}
        for b in BUCKETS:
            sel = [r for r in rows if r["bucket"] == b]
            buckets[b] = {"count": len(sel),
                          "balance": round(sum(r["balance"]
                                               for r in sel), 2)}
        out.append({
            "month_index": m,
            "month": labels[m] if m < len(labels) else str(m),
            "total_count": len(rows),
            "total_balance": round(sum(r["balance"] for r in rows), 2),
            "delinquent_count": sum(buckets[b]["count"]
                                    for b in DELINQUENT),
            "delinquent_balance": round(sum(buckets[b]["balance"]
                                            for b in DELINQUENT), 2),
            "buckets": buckets,
        })
    return out


def roll_matrix(dataset: Dict) -> Dict:
    """Month-over-month transitions, aggregated over all 11 transitions.

    ``counts[from][to]`` counts merchants; ``balances[from][to]``
    weights each transition by the merchant's balance in the FROM
    month; ``count_rates`` / ``balance_rates`` are row shares in
    percent (rows for buckets nobody leaves are all zero).
    """
    counts = {a: {b: 0 for b in BUCKETS} for a in BUCKETS}
    balances = {a: {b: 0.0 for b in BUCKETS} for a in BUCKETS}
    transitions = 0
    for prev, cur in _paired(dataset):
        counts[prev["bucket"]][cur["bucket"]] += 1
        balances[prev["bucket"]][cur["bucket"]] += prev["balance"]
        transitions += 1
    balances = {a: {b: round(v, 2) for b, v in row.items()}
                for a, row in balances.items()}

    def _rates(table, is_money):
        out = {}
        for a in BUCKETS:
            total = sum(table[a].values())
            out[a] = {b: (round(100.0 * table[a][b] / total, 4)
                          if total else 0.0) for b in BUCKETS}
        return out

    return {"transitions": transitions, "counts": counts,
            "balances": balances,
            "count_rates": _rates(counts, False),
            "balance_rates": _rates(balances, True)}


def promises_summary(dataset: Dict) -> Dict:
    """Promise-to-pay tracking per month + overall.

    **promise-to-pay (PTP)** — a delinquent merchant's commitment to
    pay an agreed amount by an agreed date; kept vs broken is the
    earliest behavioural signal in collections.
    """
    by_month = _rows_by_month(dataset)
    labels = dataset.get("month_labels") or []
    per_month = []
    tot_made = tot_kept = 0
    for m in range(MONTHS):
        rows = by_month.get(m, [])
        made = [r for r in rows if r["promise_made"]]
        kept = [r for r in made if r["promise_kept"] is True]
        tot_made += len(made)
        tot_kept += len(kept)
        per_month.append({
            "month_index": m,
            "month": labels[m] if m < len(labels) else str(m),
            "made": len(made), "kept": len(kept),
            "broken": len(made) - len(kept),
            "kept_rate": round(len(kept) / len(made), 4) if made else None,
            "promised_amount": round(sum(r["promised_amount"]
                                         for r in made), 2),
        })
    return {"per_month": per_month,
            "made": tot_made, "kept": tot_kept,
            "broken": tot_made - tot_kept,
            "kept_rate": round(tot_kept / tot_made, 4) if tot_made else None}


def cure_rates(dataset: Dict) -> Dict:
    """Per transition: share of delinquent accounts back to current."""
    per_transition = []
    delinq_total = cured_total = 0
    by_from: Dict[int, List] = {}
    for prev, cur in _paired(dataset):
        by_from.setdefault(prev["month_index"], []).append((prev, cur))
    labels = dataset.get("month_labels") or []
    for m in sorted(by_from):
        pairs = by_from[m]
        delinq = [(p, c) for p, c in pairs if p["bucket"] in DELINQUENT]
        cured = [(p, c) for p, c in delinq if c["bucket"] == "current"]
        delinq_total += len(delinq)
        cured_total += len(cured)
        per_transition.append({
            "from_month_index": m,
            "from_month": labels[m] if m < len(labels) else str(m),
            "delinquent": len(delinq), "cured": len(cured),
            "cure_rate": round(len(cured) / len(delinq), 4)
            if delinq else None,
        })
    return {"per_transition": per_transition,
            "delinquent": delinq_total, "cured": cured_total,
            "cure_rate": round(cured_total / delinq_total, 4)
            if delinq_total else None}


def monitor_payload(dataset: Dict) -> Dict:
    return {"months": MONTHS,
            "merchants": len(dataset.get("merchants", [])),
            "bucket_summary": bucket_summary(dataset),
            "cure_rates": cure_rates(dataset)}
