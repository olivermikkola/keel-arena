import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from keel_arena.quickstart import discover_suites, init_study, parse_contestant_spec
from keel_arena.results import InvalidResult, load, summarize

ROOT = Path(__file__).resolve().parents[1]
HAS_HARBOR = importlib.util.find_spec("harbor") is not None


class QuickstartAndV2Test(unittest.TestCase):
    def test_discover_suites_and_parse_contestant_spec(self):
        suites = discover_suites()
        self.assertEqual(len(suites["tasks"]), 16)
        name, entry = parse_contestant_spec("bonsai=openai/bonsai-4b@http://127.0.0.1:8080/v1|Q2_0|keel|KEY_ENV")
        self.assertEqual(name, "bonsai")
        self.assertEqual(entry["quantization"], "Q2_0")
        self.assertEqual(entry["harness"], "keel")
        self.assertEqual(entry["api_key_env"], "KEY_ENV")
        with self.assertRaises(InvalidResult):
            parse_contestant_spec("bad-spec-missing-at")

    def test_v2_summary_suites_elo_and_net_improvement(self):
        data = load(ROOT / "examples/synthetic-gauntlet-results.json")
        report = summarize(data)
        self.assertEqual(report["contestants"]["demo-edge-4b"]["grade"], "A")
        self.assertEqual(report["contestants"]["demo-edge-2b"]["grade"], "D")
        self.assertIn("coding", report["per_suite"])
        self.assertIn("instruction", report["per_suite"])
        self.assertIn("demo-edge-4b", report["elo_ratings"])
        self.assertGreater(
            report["elo_ratings"]["demo-edge-4b"]["elo"],
            report["elo_ratings"]["demo-edge-2b"]["elo"],
        )
        diff = report["paired_task_differences"][0]
        self.assertIsNotNone(diff["token_efficiency_ratio"])

    def test_init_study_cli_writes_ready_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_bin = Path(tmp) / "keel"
            fake_bin.write_bytes(b"#!/bin/sh\necho ok\n")
            out = Path(tmp) / "study.json"
            proc = subprocess.run(
                [
                    sys.executable, "-m", "keel_arena", "init-study",
                    "--binary", str(fake_bin),
                    "--suite", "coding,adversarial",
                    "--contestant", "m1=openai/qwen4-4b@http://127.0.0.1:8080/v1|Q4_K_M|keel",
                    "--contestant", "m2=openai/qwen4-4b@http://127.0.0.1:8080/v1|Q4_K_M|aider",
                    "--out", str(out),
                ],
                cwd=ROOT, capture_output=True, text=True, check=True,
            )
            res = json.loads(proc.stdout)
            self.assertEqual(res["tasks"], 4)
            self.assertEqual(res["contestants"], ["m1", "m2"])
            doc = json.loads(out.read_text())
            self.assertEqual(doc["schema_version"], 2)
            self.assertEqual(doc["contestants"]["m2"]["harness"], "aider")

            if HAS_HARBOR:
                from keel_arena.study import freeze
                freeze_dir = Path(tmp) / "frozen"
                frozen = freeze(doc, freeze_dir)
                self.assertEqual(frozen["planned_attempts"], 8)

    def test_list_suites_cli(self):
        proc = subprocess.run(
            [sys.executable, "-m", "keel_arena", "list-suites"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        data = json.loads(proc.stdout)
        self.assertEqual(len(data["tasks"]), 16)
