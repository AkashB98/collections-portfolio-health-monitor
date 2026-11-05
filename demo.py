"""End-to-end demo: generate -> validate/conservation -> monitor ->
roll -> promises/cures -> flags/backtest -> report -> check -> serve.

SYNTHETIC DATA ONLY (fictional merchants). Runs fully offline; the
serve round-trip is loopback-only on an ephemeral port.
Every stage asserts.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cli import EXIT_FAIL, EXIT_OK, main as cli_main, make_server, reset_state  # noqa: E402
from flags import backtest_flags, compute_flags  # noqa: E402
from generator import dataset_to_json, generate_dataset  # noqa: E402
from monitor import bucket_summary, cure_rates, promises_summary, roll_matrix  # noqa: E402
from report import build_markdown_report  # noqa: E402
from validation import check_conservation, validate_dataset  # noqa: E402


def _request(port: int, path: str, payload=None, method: str = "GET"):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, resp.read()


def main() -> None:
    print("== 1. generate synthetic merchant book (seed=42, 60 x 12) ==")
    data = generate_dataset()
    again = generate_dataset()
    assert data == again, "generator must be deterministic"
    assert len(data["snapshots"]) == 720 and len(data["merchants"]) == 60
    assert validate_dataset(data) == [], validate_dataset(data)[:3]
    print("   720 snapshots, deterministic re-generation verified, "
          "validation clean")

    print("\n== 2. balance conservation: every dollar accounted for ==")
    violations = check_conservation(data)
    assert violations == [], violations[:3]
    total = bucket_summary(data)[-1]["total_balance"]
    print(f"   conservation holds on all 11 transitions, to the cent; "
          f"latest book total ${total:,.2f}")

    print("\n== 3. roll rates + cures + promises ==")
    roll = roll_matrix(data)
    assert roll["transitions"] == 660
    count_total = sum(sum(r.values()) for r in roll["counts"].values())
    assert count_total == 660
    cures = cure_rates(data)
    promises = promises_summary(data)
    print(f"   cure rate overall: {cures['cure_rate']} "
          f"({cures['cured']}/{cures['delinquent']})")
    print(f"   promise kept rate overall: {promises['kept_rate']} "
          f"({promises['kept']}/{promises['made']})")
    stay = roll["count_rates"]["current"]["current"]
    print(f"   current -> current roll rate: {stay}%")

    print("\n== 4. early-risk flags + backtest (headline numbers) ==")
    bt = backtest_flags(data)
    flags = compute_flags(data)
    print(f"   flags raised: {bt['flags_total']} "
          f"(evaluated early warnings: {bt['flags_evaluated']})")
    print(f"   PRECISION: {bt['precision']}  RECALL: {bt['recall']}")
    arch = {m["merchant_id"]: m["archetype"] for m in data["merchants"]}
    flagged_ids = {f["merchant_id"] for f in flags}
    deteriorators = {mid for mid, a in arch.items()
                     if a == "deteriorating"}
    stable = {mid for mid, a in arch.items() if a == "stable_current"}
    assert deteriorators <= flagged_ids, "every deteriorator flagged"
    assert not (stable & flagged_ids), "no stable merchant flagged"

    print("\n== 5. markdown monthly readout ==")
    md = build_markdown_report(data)
    assert md == build_markdown_report(data), "report must be deterministic"
    assert "Precision" in md and "Roll rates" in md
    print("   " + md.splitlines()[2])

    print("\n== 6. CLI check gate exit codes ==")
    import tempfile
    tmp = tempfile.mkdtemp(prefix="collections-demo-")
    good_path = os.path.join(tmp, "book.json")
    with open(good_path, "w", encoding="utf-8") as fh:
        fh.write(dataset_to_json(data))
    code_ok = cli_main(["check", "--input", good_path])
    code_breach = cli_main(["check", "--input", good_path,
                            "--min-precision", "0.99",
                            "--min-recall", "0.99"])
    code_err = cli_main(["check", "--input", "/tmp/no-such-book-xyz.json"])
    print(f"   normal={code_ok} impossible-floor={code_breach} "
          f"missing-file={code_err}")
    assert code_ok == EXIT_OK and code_breach == EXIT_FAIL and code_err == 2

    print("\n== 7. live localhost serve round-trip ==")
    reset_state(data)
    server = make_server(0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _request(port, "/health")
        assert status == 200 and json.loads(body) == {"status": "ok"}
        status, body = _request(port, "/flags", payload={}, method="POST")
        served = json.loads(body)
        assert status == 200
        assert served == {"flags": flags, "backtest": bt}
        status, body = _request(port, "/report")
        assert status == 200 and body.decode() == md
        print("   POST /flags matches local computation; "
              "GET /report matches the local readout")
    finally:
        server.shutdown()
        server.server_close()
        reset_state()

    print("\nDemo OK: generate, conservation, monitor, roll, promises, "
          "flags/backtest, report, check and serve verified.")


if __name__ == "__main__":
    main()
