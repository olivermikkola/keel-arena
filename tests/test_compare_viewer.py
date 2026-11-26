"""Offline compare viewer wraps validate/report/cards without new orchestration."""

import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from keel_arena.compare_viewer import (
    OUTCOME_ORDER,
    render_compare_html,
    serve_compare_bundle,
    write_compare_bundle,
)
from keel_arena.results import load, summarize

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples/synthetic-gauntlet-results.json"


class CompareViewerTest(unittest.TestCase):
    def setUp(self):
        self.data = load(FIXTURE)
        self.report = summarize(self.data)

    def test_render_includes_purpose_outcomes_and_provenance(self):
        html_doc = render_compare_html(
            self.data,
            self.report,
            source_label="synthetic-gauntlet-results.json",
        )
        self.assertIn("demonstration", html_doc)
        self.assertIn("badge-demo", html_doc)
        self.assertIn("harness_revision", html_doc)
        self.assertIn("environment_sha256", html_doc)
        self.assertIn("sampling_sha256", html_doc)
        self.assertIn(self.report["result_sha256"][:12], html_doc)
        self.assertIn("demo-edge-2b", html_doc)
        self.assertIn("demo-edge-4b", html_doc)
        for outcome in OUTCOME_ORDER:
            self.assertIn(outcome if outcome != "infrastructure_error" else "infra", html_doc)
        self.assertIn("cards/dashboard.html", html_doc)
        self.assertIn("Open dashboard.html", html_doc)

    def test_write_bundle_emits_index_manifest_and_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "view"
            manifest = write_compare_bundle(FIXTURE, out)
            self.assertEqual(manifest["purpose"], "demonstration")
            self.assertTrue((out / "index.html").is_file())
            self.assertTrue((out / "manifest.json").is_file())
            self.assertTrue((out / "cards" / "dashboard.html").is_file())
            self.assertTrue((out / "cards" / "overview.svg").is_file())
            saved = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["result_sha256"], self.report["result_sha256"])
            self.assertEqual(
                saved["contestants"]["demo-edge-4b"]["outcomes"]["solved"],
                6,
            )
            self.assertEqual(
                saved["contestants"]["demo-edge-4b"]["outcomes"]["unsolved"],
                1,
            )
            for key in OUTCOME_ORDER:
                self.assertIn(key, saved["contestants"]["demo-edge-2b"]["outcomes"])

    def test_serve_loopback_index_and_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "view"
            write_compare_bundle(FIXTURE, out)
            ready = threading.Event()
            server, url, _thread = serve_compare_bundle(
                out, open_browser=False, ready=ready
            )
            self.assertTrue(ready.wait(timeout=5))
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    body = response.read().decode("utf-8")
                self.assertIn("Keel", body)
                self.assertIn("demonstration", body)
                dash_url = url + "cards/dashboard.html"
                with urllib.request.urlopen(dash_url, timeout=5) as response:
                    dash = response.read().decode("utf-8")
                self.assertIn("<!doctype html>", dash)
                self.assertIn("demo-edge-4b", dash)
            finally:
                server.shutdown()
                _thread.join(timeout=5)

    def test_cli_view_writes_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cli-view"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "keel_arena",
                    "view",
                    "examples/synthetic-gauntlet-results.json",
                    "--out",
                    str(out),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["purpose"], "demonstration")
            self.assertTrue((out / "index.html").is_file())
            self.assertTrue((out / "cards" / "dashboard.html").is_file())
            index = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn("Provenance digests", index)
            self.assertIn("Open dashboard.html", index)
