import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from keel_arena.cards import render_contestant_card_svg, render_dashboard_html, render_overview_svg
from keel_arena.results import load, summarize

ROOT = Path(__file__).resolve().parents[1]


class CardsTest(unittest.TestCase):
    def setUp(self):
        self.data = load(ROOT / "examples/synthetic-gauntlet-results.json")
        self.report = summarize(self.data)

    def test_svgs_are_valid_xml_and_contain_suite_and_edge_telemetry(self):
        overview = render_overview_svg(self.report)
        ET.fromstring(overview)
        self.assertIn("Keel", overview)
        self.assertIn("demo-edge-4b", overview)
        self.assertIn("85.7%", overview)

        card = render_contestant_card_svg(self.report, "demo-edge-4b")
        ET.fromstring(card)
        self.assertIn("CODING", card)
        self.assertIn("ADVERSARIAL", card)
        self.assertIn("28", card)
        self.assertIn("160K tok", card)

    def test_html_dashboard_escapes_and_includes_pareto_and_elo(self):
        html_doc = render_dashboard_html(self.report)
        self.assertIn("<!doctype html>", html_doc)
        self.assertIn("Speed vs Accuracy", html_doc)
        self.assertIn("Human Calibration Audit", html_doc)
        self.assertIn("1514", html_doc)

    def test_cli_cards_and_report_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "cards"
            proc = subprocess.run(
                [sys.executable, "-m", "keel_arena", "cards",
                 "examples/synthetic-gauntlet-results.json", "--out", str(out_dir)],
                cwd=ROOT, capture_output=True, text=True, check=True,
            )
            res = json.loads(proc.stdout)
            self.assertEqual(res["cards"], 3)
            self.assertTrue((out_dir / "overview.svg").is_file())
            self.assertTrue((out_dir / "card-demo-edge-4b.svg").is_file())
            self.assertTrue((out_dir / "card-demo-edge-2b.svg").is_file())
            self.assertTrue((out_dir / "dashboard.html").is_file())

        svg_proc = subprocess.run(
            [sys.executable, "-m", "keel_arena", "report",
             "examples/synthetic-gauntlet-results.json", "--format", "svg"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        ET.fromstring(svg_proc.stdout)

        md_proc = subprocess.run(
            [sys.executable, "-m", "keel_arena", "report",
             "examples/synthetic-gauntlet-results.json", "--format", "markdown"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        self.assertIn("## Suites", md_proc.stdout)
        self.assertIn("## Edge telemetry", md_proc.stdout)
        self.assertIn("## Pairwise Arena Elo", md_proc.stdout)
