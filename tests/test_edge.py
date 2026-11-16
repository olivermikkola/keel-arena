import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from keel_arena.edge import detect_hardware, probe_server
from keel_arena.results import InvalidResult

ROOT = Path(__file__).resolve().parents[1]


class EdgeTest(unittest.TestCase):
    def test_detect_hardware_returns_valid_structure(self):
        hw = detect_hardware()
        self.assertIn(hw["os"], ("Linux", "Darwin", "Windows"))
        self.assertIsInstance(hw["cpu_model"], str)
        self.assertTrue(hw["device_label"])
        self.assertIsInstance(hw["accelerators"], list)
        self.assertIsInstance(hw["thermals_c"], dict)

    def test_probe_server_measures_live_local_sse_streams(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == "/props":
                    body = json.dumps({
                        "default_generation_settings": {"n_ctx": 16384},
                        "total_slots": 4,
                        "model_alias": "demo-edge-slm",
                    }).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                size = int(self.headers.get("Content-Length", "0"))
                _ = self.rfile.read(size)
                events = (
                    'data: {"choices":[{"index":0,"delta":{"content":"edge "}}]}\n\n'
                    'data: {"choices":[{"index":0,"delta":{"content":"benchmark"}}]}\n\n'
                    'data: {"choices":[],"usage":{"prompt_tokens":120,"completion_tokens":8}}\n\n'
                    'data: [DONE]\n\n'
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(events)))
                self.end_headers()
                self.wfile.write(events)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            res = probe_server(
                f"http://127.0.0.1:{server.server_port}/v1",
                "demo-edge-slm",
                streams=(1, 2),
                max_tokens=16,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(res["server"]["max_context_tokens"], 16384)
        self.assertEqual(res["server"]["slots"], 4)
        self.assertEqual(res["edge_profile"]["streams_tested"], 2)
        self.assertGreater(res["edge_profile"]["speed_1_stream_tok_s"], 0)
        self.assertGreater(res["edge_profile"]["speed_n_streams_tok_s"], 0)
        self.assertGreaterEqual(res["edge_profile"]["ttft_seconds"], 0)
        self.assertEqual(len(res["profile_sha256"]), 64)

    def test_probe_server_rejects_invalid_url_and_streams(self):
        with self.assertRaises(InvalidResult):
            probe_server("ftp://invalid.local/v1", "m")
        with self.assertRaises(InvalidResult):
            probe_server("http://127.0.0.1:8080/v1", "m", streams=[0])

    def test_cli_probe_edge_hardware_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "hw.json"
            proc = subprocess.run(
                [sys.executable, "-m", "keel_arena", "probe-edge", "--out", str(out)],
                cwd=ROOT, capture_output=True, text=True, check=True,
            )
            parsed = json.loads(proc.stdout)
            self.assertEqual(parsed, json.loads(out.read_text()))
            self.assertIn("hardware", parsed)
