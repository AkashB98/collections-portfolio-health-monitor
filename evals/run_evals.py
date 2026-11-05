"""Golden evals for collections-portfolio-health-monitor.

SYNTHETIC DATA ONLY (fictional merchants). Every eval is
deterministic: run_evals.py writes eval_report.json and the file
must be byte-identical across runs. No timestamps, ports, or temp
paths enter the report — only names, booleans, pinned counts and
values.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import sys
import threading
import urllib.request
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import (EXIT_ERROR, EXIT_FAIL, EXIT_OK, load_dataset,  # noqa: E402
                 main as cli_main, make_server, reset_state)
from flags import backtest_flags, compute_flags  # noqa: E402
from generator import dataset_to_json, generate_dataset  # noqa: E402
from monitor import (bucket_summary, cure_rates,  # noqa: E402
                     promises_summary, roll_matrix)
from report import build_markdown_report  # noqa: E402
from validation import check_conservation, validate_dataset  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURE = os.path.join(ROOT, "fixtures", "sample_book.json")
RESULTS = []


def check(name, passed, detail=""):
    RESULTS.append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return passed


def _run_cli(argv):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return cli_main(argv)


def main():
    print("== golden evals: collections-portfolio-health-monitor ==")
    data = generate_dataset()
    arch = {m["merchant_id"]: m["archetype"] for m in data["merchants"]}
    flags = compute_flags(data)
    flagged_ids = {f["merchant_id"] for f in flags}
    bt = backtest_flags(data)

    # E1: generator determinism (bytes pinned)
    text1 = dataset_to_json(generate_dataset())
    text2 = dataset_to_json(generate_dataset())
    md5 = hashlib.md5(text1.encode()).hexdigest()
    check("E1 generator determinism (seed=42, 60 merchants x 12 months)",
          text1 == text2 and len(data["snapshots"]) == 720
          and md5 == "5a5ca00c92f9aa4cdc1b679ab7be24bb",
          f"dataset_md5={md5}")

    # E2: balance conservation holds on every transition, to the cent.
    violations = check_conservation(data)
    tampered = copy.deepcopy(data)
    tampered["snapshots"][100]["balance"] += 10.0
    check("E2 conservation holds all 12 months (tamper trips it)",
          violations == [] and validate_dataset(data) == []
          and len(check_conservation(tampered)) > 0,
          f"violations={len(violations)}")

    # E3: roll matrix reconciles — every transition counted once,
    # row rates sum to 100% for every bucket that is ever left.
    roll = roll_matrix(data)
    total_counts = sum(sum(r.values()) for r in roll["counts"].values())
    rates_ok = all(abs(sum(roll["count_rates"][b].values()) - 100.0) < 0.01
                   for b in roll["counts"] if any(roll["counts"][b].values()))
    check("E3 roll matrix reconciles (660 transitions, rows sum to 100%)",
          roll["transitions"] == 660 and total_counts == 660 and rates_ok,
          f"current_stay_rate={roll['count_rates']['current']['current']}")

    # E4: headline flag backtest pinned — precision 0.625 (the six
    # planted stressed_recovering merchants are the false positives),
    # recall 1.0 (every deteriorator flagged before reaching 60+).
    check("E4 flag backtest pinned (precision 0.625, recall 1.0)",
          bt["precision"] == 0.625 and bt["recall"] == 1.0
          and bt["flags_evaluated"] == 16
          and bt["true_positive_flags"] == 10
          and bt["false_positive_flags"] == 6,
          f"precision={bt['precision']} recall={bt['recall']}")

    # E5: every planted deteriorator is flagged.
    deteriorators = {mid for mid, a in arch.items()
                     if a == "deteriorating"}
    check("E5 planted deteriorators flagged (10/10)",
          deteriorators <= flagged_ids and len(deteriorators) == 10,
          f"deteriorators_flagged={len(deteriorators & flagged_ids)}")

    # E6: stable / curing / cyclical merchants are never flagged.
    quiet = {mid for mid, a in arch.items()
             if a in ("stable_current", "stable_delinquent", "curing",
                      "cyclical")}
    check("E6 stable merchants not flagged (0 false flags on quiet book)",
          not (quiet & flagged_ids), f"quiet_flagged={len(quiet & flagged_ids)}")

    # E7: promises + cures pinned on the seeded book.
    promises = promises_summary(data)
    cures = cure_rates(data)
    check("E7 promises + cures pinned (kept 79/161, cured 56/216)",
          promises["made"] == 161 and promises["kept"] == 79
          and promises["kept_rate"] == 0.4907
          and cures["cured"] == 56 and cures["delinquent"] == 216
          and cures["cure_rate"] == 0.2593,
          f"kept_rate={promises['kept_rate']} cure_rate={cures['cure_rate']}")

    # E8: CLI check exit codes 0 / 1 / 2.
    import tempfile
    tmp = tempfile.mkdtemp(prefix="collections-evals-")
    good_path = os.path.join(tmp, "book.json")
    with open(good_path, "w", encoding="utf-8") as fh:
        fh.write(dataset_to_json(data))
    codes = (_run_cli(["check", "--input", good_path]),
             _run_cli(["check", "--input", good_path,
                       "--min-precision", "0.99"]),
             _run_cli(["check", "--input", "/tmp/no-such-book-xyz.json"]))
    check("E8 CLI check exit codes 0/1/2",
          codes == (EXIT_OK, EXIT_FAIL, EXIT_ERROR), f"codes={codes}")

    # E9: serve round-trip matches local computation.
    reset_state(data)
    server = make_server(0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health",
                                    timeout=10) as resp:
            health = json.loads(resp.read())
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/flags", data=b"{}",
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            served = json.loads(resp.read())
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/report",
                                    timeout=10) as resp:
            served_report = resp.read().decode()
        serve_ok = health == {"status": "ok"} \
            and served == {"flags": flags, "backtest": bt} \
            and served_report == build_markdown_report(data)
    finally:
        server.shutdown()
        server.server_close()
        reset_state()
    check("E9 serve round-trip matches local flags + report", serve_ok)

    # E10: bundled fixture pinned (720 snapshots, clean, totals pinned).
    fixture = load_dataset(FIXTURE)
    last = bucket_summary(fixture)[-1]
    check("E10 fixture pinned (720 snapshots, latest total $1,203,450.19)",
          fixture == data and len(fixture["snapshots"]) == 720
          and validate_dataset(fixture) == []
          and last["total_balance"] == 1203450.19,
          f"latest_total={last['total_balance']}")

    # E11: report determinism — markdown identical across builds.
    md1 = build_markdown_report(data)
    md2 = build_markdown_report(generate_dataset())
    check("E11 report determinism (markdown identical)",
          md1 == md2, f"report_md5={hashlib.md5(md1.encode()).hexdigest()}")

    passed = sum(1 for r in RESULTS if r["passed"])
    total_count = len(RESULTS)
    summary_doc = {"passed": passed, "total": total_count,
                   "all_passed": passed == total_count, "evals": RESULTS}
    with open(os.path.join(HERE, "eval_report.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(summary_doc, sort_keys=True) + "\n")
    print(f"\n{passed}/{total_count} evals passed -> evals/eval_report.json")
    return 0 if passed == total_count else 1


if __name__ == "__main__":
    sys.exit(main())
