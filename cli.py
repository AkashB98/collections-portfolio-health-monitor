"""CLI: generate | monitor | roll | promises | flags | report |
check | demo | serve.

SYNTHETIC DATA ONLY — every merchant is fictional and every dataset
handled here is fabricated sample data.

Exit codes:
  check : 0 = pass, 1 = flag-quality breach (backtest precision or
          recall below its floor), 2 = usage / IO / data-quality
          error (including any balance-conservation violation)
  others: 0 = success, 2 = usage / IO error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flags import backtest_flags, compute_flags  # noqa: E402
from generator import generate_dataset, dataset_to_json  # noqa: E402
from monitor import (bucket_summary, cure_rates, monitor_payload,  # noqa: E402
                     promises_summary, roll_matrix)
from report import build_markdown_report  # noqa: E402
from validation import check_conservation, validate_dataset  # noqa: E402

EXIT_OK, EXIT_FAIL, EXIT_ERROR = 0, 1, 2
DEFAULT_MIN_PRECISION = 0.5
DEFAULT_MIN_RECALL = 0.8


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True)


def load_dataset(path: str) -> Dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("dataset file must contain a JSON object")
    return data


def _load_or_error(path: str) -> Optional[Dict]:
    try:
        return load_dataset(path)
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
    except (ValueError, OSError) as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
    return None


def _validated(args):
    data = _load_or_error(args.input)
    if data is None:
        return None, EXIT_ERROR
    issues = validate_dataset(data)
    if issues:
        for issue in issues[:20]:
            print(f"data-quality: {issue}", file=sys.stderr)
        return None, EXIT_ERROR
    return data, EXIT_OK


def _write_out(args, text: str, summary: str) -> int:
    if getattr(args, "out", None):
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            print(f"error: cannot write {args.out}: {exc}", file=sys.stderr)
            return EXIT_ERROR
        print(summary)
    else:
        print(text, end="")
    return EXIT_OK


def cmd_generate(args) -> int:
    data = generate_dataset(seed=args.seed, merchants=args.merchants)
    return _write_out(args, dataset_to_json(data),
                      f"generated synthetic book: {args.merchants} "
                      f"merchants x 12 months (seed={args.seed}) "
                      f"-> {args.out}")


def cmd_monitor(args) -> int:
    data, code = _validated(args)
    if data is None:
        return code
    return _write_out(args, canonical(monitor_payload(data)) + "\n",
                      f"monitor -> {args.out}")


def cmd_roll(args) -> int:
    data, code = _validated(args)
    if data is None:
        return code
    return _write_out(args, canonical(roll_matrix(data)) + "\n",
                      f"roll -> {args.out}")


def cmd_promises(args) -> int:
    data, code = _validated(args)
    if data is None:
        return code
    payload = {"promises": promises_summary(data),
               "cure_rates": cure_rates(data)}
    return _write_out(args, canonical(payload) + "\n",
                      f"promises -> {args.out}")


def cmd_flags(args) -> int:
    data, code = _validated(args)
    if data is None:
        return code
    payload = {"flags": compute_flags(data),
               "backtest": backtest_flags(data)}
    return _write_out(args, canonical(payload) + "\n",
                      f"flags -> {args.out}")


def cmd_report(args) -> int:
    data, code = _validated(args)
    if data is None:
        return code
    return _write_out(args, build_markdown_report(data),
                      f"report -> {args.out}")


def cmd_check(args) -> int:
    data = _load_or_error(args.input)
    if data is None:
        return EXIT_ERROR
    issues = validate_dataset(data)
    if issues:
        for issue in issues[:20]:
            print(f"data-quality: {issue}")
        print(f"check FAIL (data quality): {len(issues)} issue(s)")
        return EXIT_ERROR
    bt = backtest_flags(data)
    print(f"merchants={len(data.get('merchants', []))} "
          f"months=12 conservation=ok "
          f"precision={bt['precision']} recall={bt['recall']} "
          f"min_precision={args.min_precision} "
          f"min_recall={args.min_recall}")
    if bt["precision"] < args.min_precision \
            or bt["recall"] < args.min_recall:
        print(f"check FAIL: flag quality below floor "
              f"(precision {bt['precision']} / recall {bt['recall']})")
        return EXIT_FAIL
    print("check PASS")
    return EXIT_OK


def cmd_demo(args) -> int:
    import demo as demo_mod
    try:
        demo_mod.main()
    except AssertionError as exc:
        print(f"demo FAILED: {exc}", file=sys.stderr)
        return EXIT_FAIL
    return EXIT_OK


# ------------------------------------------------------------------- serve

class _State:
    def __init__(self):
        self.data: Dict = generate_dataset()


_STATE = _State()


def get_state() -> _State:
    return _STATE


def reset_state(data: Optional[Dict] = None) -> None:
    _STATE.data = data if data is not None else generate_dataset()


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, payload: Any) -> None:
        self._send(code, (canonical(payload) + "\n").encode(),
                   "application/json")

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            return self._send_json(200, {"status": "ok"})
        if self.path == "/report":
            return self._send(200, build_markdown_report(
                _STATE.data).encode(), "text/markdown; charset=utf-8")
        return self._send_json(404, {"error": "unknown endpoint"})

    def do_POST(self):  # noqa: N802
        if self.path != "/flags":
            return self._send_json(404, {"error": "unknown endpoint"})
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw) if raw.strip() else {}
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
            data = _STATE.data
            if "dataset" in body:
                candidate = body["dataset"]
                issues = validate_dataset(candidate)
                if issues:
                    return self._send_json(
                        400, {"error": f"data quality: {issues[0]}"})
                data = candidate
                _STATE.data = candidate
            payload = {"flags": compute_flags(data),
                       "backtest": backtest_flags(data)}
            return self._send_json(200, payload)
        except (ValueError, TypeError, KeyError) as exc:
            return self._send_json(400, {"error": f"bad request: {exc}"})

    def log_message(self, *a: Any) -> None:
        pass


def make_server(port: int) -> HTTPServer:
    return HTTPServer(("127.0.0.1", port), _Handler)


def cmd_serve(args) -> int:
    if args.input:
        data = _load_or_error(args.input)
        if data is None:
            return EXIT_ERROR
        reset_state(data)
    server = make_server(args.port)
    print(f"serving on http://127.0.0.1:{args.port}  "
          f"(POST /flags, GET /report, GET /health)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="collections-portfolio-health-monitor",
        description="Live merchant arrears book monitoring: buckets, "
                    "roll rates, promises, cures, early-risk flags.")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="generate the synthetic book")
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--merchants", type=int, default=60)
    g.add_argument("--out", default=None)
    g.set_defaults(func=cmd_generate)

    for name, func, helptext in [
            ("monitor", cmd_monitor, "bucket summary + cure rates"),
            ("roll", cmd_roll, "roll-rate matrix (count + balance)"),
            ("promises", cmd_promises, "promise-to-pay + cure tracking"),
            ("flags", cmd_flags, "early-risk flags + backtest"),
            ("report", cmd_report, "markdown monthly readout")]:
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--input", required=True)
        s.add_argument("--out", default=None)
        s.set_defaults(func=func)

    c = sub.add_parser("check", help="CI gate: exit 0 pass / 1 breach / 2 error")
    c.add_argument("--input", required=True)
    c.add_argument("--min-precision", type=float,
                   default=DEFAULT_MIN_PRECISION)
    c.add_argument("--min-recall", type=float, default=DEFAULT_MIN_RECALL)
    c.set_defaults(func=cmd_check)

    sub.add_parser("demo", help="run the end-to-end demo").set_defaults(func=cmd_demo)

    s = sub.add_parser("serve", help="localhost JSON/markdown API")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--input", default=None)
    s.set_defaults(func=cmd_serve)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
