"""Offline compare viewer wraps validate/report/cards and paired compare_runs."""

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
    compare_arena_results,
    detect_run_kind,
    render_compare_html,
    render_paired_compare_html,
    serve_compare_bundle,
    write_compare_bundle,
    write_paired_compare_bundle,
)
from keel_arena.results import InvalidResult, load, summarize

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples/synthetic-gauntlet-results.json"
RESULTS_A = ROOT / "examples/synthetic-results.json"
RESULTS_B = ROOT / "examples/synthetic-results-paired-b.json"
MOBILE_LEFT = ROOT / "examples/synthetic-keel-mobile/base-run"
MOBILE_RIGHT = ROOT / "examples/synthetic-keel-mobile/adapted-run"


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
            self.assertEqual(manifest["kind"], "arena_single_compare")
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

    def test_detect_run_kind(self):
        self.assertEqual(detect_run_kind(FIXTURE), "arena_results")
        self.assertEqual(detect_run_kind(MOBILE_LEFT), "keel_mobile")
        with self.assertRaises(InvalidResult):
            detect_run_kind(ROOT / "docs/compare-viewer.md")

    def test_compare_arena_results_matrix_diffs(self):
        left = load(RESULTS_A)
        right = load(RESULTS_B)
        report = compare_arena_results(left, right, left_label="base", right_label="adapted")
        self.assertEqual(report["kind"], "arena_results_paired_comparison")
        self.assertEqual(report["purpose"], "demonstration")
        self.assertTrue(any(d["field"] == "sampling_sha256" for d in report["setup_differences"]))
        self.assertGreaterEqual(len(report["changed_tasks"]), 1)
        self.assertTrue(any(t["task"] == "toy-git" for t in report["timeouts"]))
        self.assertTrue(
            any(
                e["task"] == "toy-edit" and e["contestant"] == "demo-a"
                for e in report["excluded_infrastructure_attempts"]
            )
        )
        html_doc = render_paired_compare_html(
            report,
            left_dashboard_href="left/cards/dashboard.html",
            right_dashboard_href="right/cards/dashboard.html",
            source_left=RESULTS_A.name,
            source_right=RESULTS_B.name,
        )
        self.assertIn("Paired Compare", html_doc)
        self.assertIn("Changed tasks", html_doc)
        self.assertIn("Timeouts", html_doc)
        self.assertIn("sampling_sha256", html_doc)
        self.assertIn("badge-demo", html_doc)
        self.assertIn("left/cards/dashboard.html", html_doc)

    def test_write_paired_arena_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "paired-results"
            manifest = write_paired_compare_bundle(
                RESULTS_A,
                RESULTS_B,
                out,
                left_label="base",
                right_label="adapted",
            )
            self.assertEqual(manifest["artifact_kind"], "arena_results")
            self.assertEqual(manifest["purpose"], "demonstration")
            self.assertTrue((out / "index.html").is_file())
            self.assertTrue((out / "paired.json").is_file())
            self.assertTrue((out / "left" / "cards" / "dashboard.html").is_file())
            self.assertTrue((out / "right" / "cards" / "dashboard.html").is_file())
            index = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn("Changed tasks", index)
            self.assertIn("Infra exclusions", index)
            paired = json.loads((out / "paired.json").read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(paired["changed_tasks"]), 1)

    def test_write_paired_mobile_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "paired-mobile"
            manifest = write_paired_compare_bundle(
                MOBILE_LEFT,
                MOBILE_RIGHT,
                out,
                left_label="base",
                right_label="adapted",
            )
            self.assertEqual(manifest["artifact_kind"], "keel_mobile")
            self.assertEqual(manifest["kind"], "keel_mobile_paired_comparison")
            self.assertTrue((out / "index.html").is_file())
            self.assertTrue((out / "paired.json").is_file())
            self.assertIsNone(manifest["cards"])
            index = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn("Changed tasks", index)
            self.assertIn("Provenance / setup diffs", index)
            paired = json.loads((out / "paired.json").read_text(encoding="utf-8"))
            self.assertIn("setup_differences", paired)
            self.assertIn("changed_tasks", paired)

    def test_cli_view_paired_mobile_and_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            mobile_out = Path(tmp) / "cli-mobile"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "keel_arena",
                    "view",
                    "examples/synthetic-keel-mobile/base-run",
                    "--against",
                    "examples/synthetic-keel-mobile/adapted-run",
                    "--out",
                    str(mobile_out),
                    "--left-label",
                    "base",
                    "--right-label",
                    "adapted",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["artifact_kind"], "keel_mobile")
            self.assertGreaterEqual(payload["changed_tasks"], 0)
            self.assertIn("Paired Compare", (mobile_out / "index.html").read_text(encoding="utf-8"))

            results_out = Path(tmp) / "cli-results"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "keel_arena",
                    "view",
                    "examples/synthetic-results.json",
                    "--against",
                    "examples/synthetic-results-paired-b.json",
                    "--out",
                    str(results_out),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["artifact_kind"], "arena_results")
            self.assertGreaterEqual(payload["timeouts"], 1)
            self.assertGreaterEqual(payload["excluded_infrastructure_attempts"], 1)

    def test_mixed_kinds_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(InvalidResult):
                write_paired_compare_bundle(FIXTURE, MOBILE_LEFT, Path(tmp) / "mixed")
