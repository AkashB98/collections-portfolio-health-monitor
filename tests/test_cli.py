import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import (EXIT_ERROR, EXIT_FAIL, EXIT_OK, load_dataset,  # noqa: E402
                 main as cli_main, make_server, reset_state)
from flags import backtest_flags, compute_flags
from generator import dataset_to_json, generate_dataset
from report import build_markdown_report


def _run(argv):
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(io.StringIO()):
        code = cli_main(argv)
    return code, out.getvalue()


class TestCli(unittest.TestCase):
    def setUp(self):
        self.data = generate_dataset()
        self.tmp = tempfile.mkdtemp(prefix="collections-cli-")
        self.path = os.path.join(self.tmp, "book.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(dataset_to_json(self.data))

    def test_generate_stdout_is_loadable(self):
        code, text = _run(["generate"])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(text)["snapshots"],
                         self.data["snapshots"])

    def test_monitor_roll_promises_flags(self):
        code, text = _run(["monitor", "--input", self.path])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(text)["merchants"], 60)
        code, text = _run(["roll", "--input", self.path])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(text)["transitions"], 660)
        code, text = _run(["promises", "--input", self.path])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(text)["promises"]["made"], 161)
        code, text = _run(["flags", "--input", self.path])
        self.assertEqual(code, EXIT_OK)
        payload = json.loads(text)
        self.assertEqual(payload["backtest"]["precision"], 0.625)
        self.assertEqual(payload["flags"], compute_flags(self.data))

    def test_report_is_markdown(self):
        code, text = _run(["report", "--input", self.path])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(text, build_markdown_report(self.data))
        self.assertTrue(text.startswith("# Collections portfolio health"))

    def test_check_exit_codes(self):
        code, _ = _run(["check", "--input", self.path])
        self.assertEqual(code, EXIT_OK)
        code, _ = _run(["check", "--input", self.path,
                        "--min-precision", "0.99"])
        self.assertEqual(code, EXIT_FAIL)
        code, _ = _run(["check", "--input", "/tmp/no-such-book-xyz.json"])
        self.assertEqual(code, EXIT_ERROR)

    def test_check_data_quality_is_exit_2(self):
        bad = generate_dataset()
        bad["snapshots"][10]["balance"] = -5.0
        bad_path = os.path.join(self.tmp, "bad.json")
        with open(bad_path, "w", encoding="utf-8") as fh:
            fh.write(dataset_to_json(bad))
        code, _ = _run(["check", "--input", bad_path])
        self.assertEqual(code, EXIT_ERROR)

    def test_load_dataset_rejects_non_object(self):
        bad_path = os.path.join(self.tmp, "list.json")
        with open(bad_path, "w", encoding="utf-8") as fh:
            fh.write("[1, 2, 3]")
        code, _ = _run(["monitor", "--input", bad_path])
        self.assertEqual(code, EXIT_ERROR)
        with self.assertRaises(ValueError):
            load_dataset(bad_path)


class TestServe(unittest.TestCase):
    def setUp(self):
        self.data = generate_dataset()
        reset_state(self.data)
        self.server = make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        reset_state()

    def _req(self, path, payload=None, method="GET", raw=False):
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"} if data else {}
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read()
                return resp.status, (body if raw else json.loads(body))
        except urllib.error.HTTPError as exc:
            body = exc.read()
            return exc.code, (body if raw else json.loads(body))

    def test_health(self):
        status, body = self._req("/health")
        self.assertEqual((status, body), (200, {"status": "ok"}))

    def test_post_flags_matches_local(self):
        status, body = self._req("/flags", {}, method="POST")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"flags": compute_flags(self.data),
                                "backtest": backtest_flags(self.data)})

    def test_get_report_matches_local(self):
        status, body = self._req("/report", raw=True)
        self.assertEqual(status, 200)
        self.assertEqual(body.decode(), build_markdown_report(self.data))

    def test_unknown_endpoint_404(self):
        status, _ = self._req("/nope")
        self.assertEqual(status, 404)
        status, _ = self._req("/flags")  # GET not supported
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
