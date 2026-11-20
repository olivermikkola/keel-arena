"""Unit tests for offline paired comparison of saved Keel Mobile eval runs."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from keel_arena.__main__ import main
from keel_arena.keel_mobile import (
    classify,
    classify_stop,
    compare_runs,
    load_run,
    markdown,
    parse_attempts,
    parse_header,
    parse_server_log,
    parse_setup_pairs,
)
from keel_arena.results import InvalidResult

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples/synthetic-keel-mobile"


class KeelMobileCompareTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _row(self, **overrides):
        base = {
            "task": "demo-task",
            "sample": 0,
            "success": True,
            "answered": True,
            "grounded": True,
            "steps": 1,
            "rejected": 0,
            "toolErrors": 0,
            "proposals": 0,
            "staleProposals": 0,
            "scriptCalls": 0,
            "userTurns": 1,
            "prefillTokens": 500,
            "cacheMisses": 1,
            "generatedTokens": 50,
            "wrappedCalls": 0,
            "callSteps": 1,
            "narrationCharacters": 8,
            "seconds": 2.5,
            "answer": "ok",
            "checkOutput": "",
            "transcript": [],
        }
        base.update(overrides)
        return base

    def _write_run(self, name, rows_by_suite, *, model_sha="1" * 64, model_file="a.gguf",
                   commit="a" * 40, server_log=None, headers=None):
        run_dir = self.root / name
        run_dir.mkdir(parents=True, exist_ok=True)
        if model_sha:
            (run_dir / "model.sha256").write_text(f"{model_sha}  {model_file}\n", encoding="utf-8")
        if commit:
            (run_dir / "keel-mobile-commit.txt").write_text(f"{commit}\n", encoding="utf-8")
        if server_log:
            (run_dir / "server.log").write_text(server_log, encoding="utf-8")
        for suite, rows in rows_by_suite.items():
            (run_dir / f"{suite}.jsonl").write_text(
                "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
            )
            if headers and suite in headers:
                (run_dir / f"{suite}.txt").write_text(headers[suite], encoding="utf-8")
            else:
                tasks = len({r["task"] for r in rows})
                samples = max((r["sample"] for r in rows), default=0) + 1
                passed = sum(1 for r in rows if r["success"])
                (run_dir / f"{suite}.txt").write_text(
                    f"model: {model_file}  family: lfm3  grammar: on  tools: workspace  "
                    f"context: 32768  samples: {samples}  tasks: {tasks}\n"
                    f"sampler: top_k 50, top_p 1.0, temperature 0.1, presence_penalty 0.0, "
                    f"min_p 0.0, repeat_penalty 1.1\n"
                    f"all      {passed}/{len(rows)} passed · mean steps 1.0\n",
                    encoding="utf-8",
                )
        return run_dir

    def test_synthetic_fixture_cli_and_markdown_roundtrip(self):
        left = load_run(FIXTURE / "base-run")
        right = load_run(FIXTURE / "adapted-run")
        report = compare_runs(left, right)
        self.assertEqual(report["matched_attempts"], 4)
        self.assertEqual(report["totals"]["left"]["solved"], 2)
        self.assertEqual(report["totals"]["right"]["solved"], 2)
        self.assertEqual(report["totals"]["solved_difference"], 0)
        self.assertEqual(report["totals"]["right"]["outcomes"]["timeout"], 2)
        self.assertEqual(report["totals"]["right"]["script_calls"], 8)
        self.assertEqual(report["totals"]["left"]["narration_characters"], 30)
        self.assertEqual(report["totals"]["right"]["narration_characters"], 0)
        self.assertEqual(len(report["changed_tasks"]), 2)
        self.assertEqual(len(report["timeouts"]), 2)
        self.assertEqual(report["warnings"], [])
        md = markdown(report)
        self.assertIn("# Keel Mobile paired comparison", md)
        self.assertIn("demo-chain", md)
        self.assertIn("timeout:step_limit", md)

        out_json = self.root / "report.json"
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([
                "compare-keel-mobile",
                str(FIXTURE / "base-run"),
                "--against",
                str(FIXTURE / "adapted-run"),
                "--out",
                str(out_json),
            ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out_json.read_text(encoding="utf-8")), report)

        out_md = self.root / "report.md"
        with redirect_stdout(io.StringIO()):
            code_md = main([
                "compare-keel-mobile",
                str(FIXTURE / "base-run"),
                "--against",
                str(FIXTURE / "adapted-run"),
                "--format",
                "markdown",
                "--out",
                str(out_md),
            ])
        self.assertEqual(code_md, 0)
        self.assertEqual(out_md.read_text(encoding="utf-8"), md)

    def test_classify_stop_and_outcomes(self):
        self.assertEqual(classify_stop(None), (None, None))
        self.assertEqual(classify_stop("tool limit"), ("timeout", "step_limit"))
        self.assertEqual(classify_stop("invalid call at limit"), ("timeout", "step_limit"))
        self.assertEqual(classify_stop("call cut off by the reply limit"), ("timeout", "reply_limit"))
        self.assertEqual(classify_stop("context overflow"), ("timeout", "context_limit"))
        self.assertEqual(classify_stop("invalid call: <tool_call>foo"), ("unsolved", "invalid_call"))
        self.assertEqual(classify_stop("tool failure: call"), ("unsolved", "invalid_call"))
        self.assertEqual(
            classify_stop("error: Error Domain=NSURLErrorDomain Code=-1001 'The request timed out.'"),
            ("timeout", "request_timeout"),
        )
        self.assertEqual(classify_stop("tool failure: sqlite disk IO"), ("infrastructure_error", "tool_failure"))
        self.assertEqual(classify_stop("error: connection refused"), ("infrastructure_error", "harness_error"))
        self.assertEqual(classify_stop("mystery stop"), ("infrastructure_error", "unreviewed_stop"))

        self.assertEqual(
            classify(self._row(success=False, checkOutput="check could not run: missing python")),
            ("infrastructure_error", "check_error"),
        )
        self.assertEqual(classify(self._row(success=True)), ("solved", None))
        self.assertEqual(classify(self._row(success=False)), ("unsolved", None))

    def test_speed_shift_warns_until_declared_setup_is_provided(self):
        cpu_log = (
            "0.00.001 I srv llama_server: initializing ...\n"
            "0.00.100 I cmn init: llama threadpool init, n_threads = 8\n"
            "0.01.000 I slot print_timing: id 0 | task 0 | prompt eval time = 1000.00 ms / 320 tokens\n"
            "0.02.000 I slot print_timing: id 0 | task 0 |        eval time = 1000.00 ms / 40 tokens\n"
        )
        vk_log = (
            "0.00.001 I srv llama_server: initializing ...\n"
            "0.00.100 I cmn init: llama threadpool init, n_threads = 8\n"
            "0.01.000 I slot print_timing: id 0 | task 0 | prompt eval time = 1000.00 ms / 1600 tokens\n"
            "0.02.000 I slot print_timing: id 0 | task 0 |        eval time = 1000.00 ms / 50 tokens\n"
        )
        rows_a = [self._row(task="t1", sample=0, success=True)]
        rows_b = [self._row(task="t1", sample=0, success=False)]
        dir_a = self._write_run("cpu", {"work": rows_a}, server_log=cpu_log)
        dir_b = self._write_run("vk", {"work": rows_b}, server_log=vk_log)

        undeclared = compare_runs(load_run(dir_a), load_run(dir_b))
        self.assertEqual(undeclared["observed_speed"]["observed_prompt_tok_s"]["ratio"], 5.0)
        self.assertTrue(any("1.5x or more" in w for w in undeclared["warnings"]))
        self.assertTrue(any("no recorded or declared setup difference" in w for w in undeclared["warnings"]))

        declared = compare_runs(
            load_run(dir_a, parse_setup_pairs(["backend=cpu"])),
            load_run(dir_b, parse_setup_pairs(["backend=vulkan"])),
        )
        self.assertEqual(declared["warnings"], [])
        self.assertEqual(
            declared["setup_differences"],
            [{"field": "declared.backend", "suites": "all", "left": "cpu", "right": "vulkan"}],
        )

    def test_infrastructure_error_and_one_sided_cells_excluded(self):
        rows_a = [
            self._row(task="t1", sample=0, success=True),
            self._row(task="t2", sample=0, success=False, fatal="error: server crashed"),
            self._row(task="t3", sample=0, success=True),
        ]
        rows_b = [
            self._row(task="t1", sample=0, success=False),
            self._row(task="t2", sample=0, success=True),
        ]
        dir_a = self._write_run("a", {"work": rows_a, "repo": [self._row(task="r1", sample=0)]}, model_sha="1" * 64)
        dir_b = self._write_run("b", {"work": rows_b}, model_sha="2" * 64)
        report = compare_runs(load_run(dir_a), load_run(dir_b))
        self.assertEqual(report["matched_attempts"], 1)
        self.assertEqual(len(report["excluded_infrastructure_attempts"]), 1)
        self.assertEqual(report["one_side_only"]["left"], ["work/t3#0"])
        self.assertEqual(report["not_compared_suites"]["left"], ["repo"])
        md = markdown(report)
        self.assertIn("## Not compared", md)
        self.assertIn("work/t2#0: infrastructure error excluded on both sides", md)
        self.assertIn("recorded only in a: work/t3#0", md)
        self.assertIn("suites only in a: repo", md)

    def test_invalid_inputs_and_symlinks_fail_closed(self):
        with self.assertRaises(InvalidResult):
            parse_attempts(b'{"task":"../bad","sample":0,"success":true,"seconds":1}\n')
        with self.assertRaises(InvalidResult):
            parse_attempts(b'{"task":"t","sample":0,"success":true,"seconds":1}\n'
                           b'{"task":"t","sample":0,"success":false,"seconds":1}\n')
        with self.assertRaises(InvalidResult):
            parse_setup_pairs(["BAD_KEY=1"])
        with self.assertRaises(InvalidResult):
            parse_setup_pairs(["backend=a", "backend=b"])

        link = self.root / "symlink-run"
        link.symlink_to(FIXTURE / "base-run")
        with self.assertRaises(InvalidResult):
            load_run(link)

        err = io.StringIO()
        with redirect_stderr(err):
            code = main(["compare-keel-mobile", str(link), "--against", str(FIXTURE / "adapted-run")])
        self.assertEqual(code, 2)
        self.assertNotIn(str(link), err.getvalue())

    def test_single_jsonl_file_comparison_and_duplicate_labels(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([
                "compare-keel-mobile",
                str(FIXTURE / "base-run/work.jsonl"),
                "--against",
                str(FIXTURE / "adapted-run/work.jsonl"),
            ])
        self.assertEqual(code, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["left"]["label"], "work (left)")
        self.assertEqual(data["right"]["label"], "work (right)")
        self.assertEqual(data["matched_attempts"], 4)


if __name__ == "__main__":
    unittest.main()
