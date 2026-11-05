"""Monthly readout — a clean markdown report, not a dashboard.

Assembles the bucket summary, the latest roll matrix, promises,
cures, and the flagged merchants into deterministic markdown copied
from the computed numbers (never recomputed in the text layer).
"""

from __future__ import annotations

from typing import Dict

from flags import backtest_flags, compute_flags
from generator import BUCKETS
from monitor import bucket_summary, cure_rates, promises_summary, roll_matrix


def _money(v: float) -> str:
    return f"${v:,.2f}"


def build_markdown_report(dataset: Dict) -> str:
    summary = bucket_summary(dataset)
    roll = roll_matrix(dataset)
    promises = promises_summary(dataset)
    cures = cure_rates(dataset)
    bt = backtest_flags(dataset)
    flags = compute_flags(dataset)
    first, last = summary[0], summary[-1]
    lines = [
        "# Collections portfolio health — monthly readout",
        "",
        f"Book: {last['total_count']} fictional merchants, "
        f"{first['month']} → {last['month']} (synthetic data only).",
        "",
        "## Book at a glance",
        "",
        f"- Total balance: {_money(first['total_balance'])} → "
        f"{_money(last['total_balance'])}",
        f"- Delinquent accounts (1-30 or worse, not written off): "
        f"{first['delinquent_count']} → {last['delinquent_count']} "
        f"({_money(last['delinquent_balance'])} at the latest month)",
        f"- Overall promise-to-pay kept rate: "
        f"{promises['kept_rate']} ({promises['kept']}/{promises['made']})",
        f"- Overall cure rate: {cures['cure_rate']} "
        f"({cures['cured']}/{cures['delinquent']} delinquent transitions)",
        "",
        "## Balances by bucket (latest month)",
        "",
        "| Bucket | Accounts | Balance |",
        "|---|---|---|",
    ]
    for b in BUCKETS:
        cell = last["buckets"][b]
        lines.append(f"| {b} | {cell['count']} | "
                     f"{_money(cell['balance'])} |")
    lines += [
        "",
        "## Roll rates (count %, all transitions)",
        "",
        "| From \\ To | " + " | ".join(BUCKETS) + " |",
        "|" + "---|" * (len(BUCKETS) + 1),
    ]
    for a in BUCKETS:
        row = roll["count_rates"][a]
        lines.append(f"| {a} | " + " | ".join(f"{row[b]:.1f}"
                                              for b in BUCKETS) + " |")
    lines += [
        "",
        "## Early-risk flags — backtest",
        "",
        f"- Flags raised: {bt['flags_total']} "
        f"({bt['flags_evaluated']} evaluated as early warnings)",
        f"- Precision: {bt['precision']} — of the evaluated flags, "
        f"this share reached 60+ within two months",
        f"- Recall: {bt['recall']} — of the {bt['rollers']} merchants "
        f"who ever reached 60+, this share was flagged in the two "
        f"months before",
        "",
        "## Latest flags",
        "",
    ]
    if flags:
        for f in flags[-10:]:
            lines.append(f"- {f['month']} · {f['merchant_id']} "
                         f"({f['merchant_name']}) · {f['bucket']} · "
                         f"{_money(f['balance'])} · "
                         f"{', '.join(f['reasons'])}")
    else:
        lines.append("- None.")
    lines += [
        "",
        "Synthetic data only — every merchant and every dollar above "
        "is fabricated by the seeded generator.",
        "",
    ]
    return "\n".join(lines)


def report_payload(dataset: Dict) -> Dict:
    """JSON companion to the markdown readout (used by evals/tests)."""
    return {
        "bucket_summary": bucket_summary(dataset),
        "roll": roll_matrix(dataset),
        "promises": promises_summary(dataset),
        "cure_rates": cure_rates(dataset),
        "backtest": backtest_flags(dataset),
        "flags": compute_flags(dataset),
        "markdown": build_markdown_report(dataset),
    }
