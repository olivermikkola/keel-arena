"""Offline reporting, frontier LLM judging, edge profiling, and private Harbor studies."""

import argparse
import json
import os
import sys
import threading
from pathlib import Path

from .harbor_import import import_trials, read_json
from .results import InvalidResult, load, summarize


def _read_bounded_json(path):
    with Path(path).open("rb") as source:
        raw = source.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise InvalidResult("input exceeds 16 MiB")
    return read_json(raw)


def _write_json_out(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(prog="keel-arena")
    parser.add_argument(
        "command",
        choices=(
            "validate",
            "report",
            "import-harbor",
            "freeze-study",
            "run-study",
            "export-trace",
            "list-suites",
            "init-study",
            "probe-edge",
            "judge",
            "judge-pairwise",
            "calibrate",
            "cards",
            "compare-keel-mobile",
            "view",
        ),
    )
    parser.add_argument("result", nargs="?", help="path to input JSON file or directory")
    parser.add_argument("--jobs-root", help="local Harbor jobs directory for import-harbor")
    parser.add_argument("--out", help="output file or directory")
    parser.add_argument("--resume", action="store_true", help="resume verified cells in run-study")
    parser.add_argument("--pass-k", default="1,2,4,8", help="comma-separated k values for report")
    parser.add_argument(
        "--format",
        choices=("json", "markdown", "svg", "html"),
        default="json",
        help="report output format",
    )
    # init-study / list-suites
    parser.add_argument("--suite", default="gauntlet", help="suite selection: all, gauntlet, repair, or comma list")
    parser.add_argument("--binary", help="path to keel executable for init-study")
    parser.add_argument("--contestant", action="append", default=[], help="name=model@base_url[|quant|harness|KEY_ENV]")
    parser.add_argument("--repetitions", type=int, default=1, help="repetitions per task for init-study")
    parser.add_argument("--thermal-limit", type=int, default=65, help="CPU thermal limit C for init-study")
    parser.add_argument("--probe-edge", action="store_true", help="probe contestant endpoints during init-study")
    # probe-edge / judge shared options
    parser.add_argument("--base-url", help="OpenAI-compatible endpoint base URL")
    parser.add_argument("--model", help="model identifier for probe-edge or judge")
    parser.add_argument("--api-key-env", default=None, help="environment variable holding API key")
    parser.add_argument("--streams", default="1,4", help="comma-separated concurrent stream counts for probe-edge")
    # judge / calibrate options
    parser.add_argument("--rubric", help="path to rubric JSON for judge commands")
    parser.add_argument("--overrides", help="path to human calibration overrides JSON")
    parser.add_argument("--results", help="optional results JSON to update during calibrate")
    parser.add_argument("--seed", type=int, default=0, help="judge RNG seed")
    # compare-keel-mobile / view --against options
    parser.add_argument(
        "--against",
        help="right-hand run for compare-keel-mobile or paired view (results JSON or Keel Mobile dir)",
    )
    parser.add_argument("--suites", help="comma-separated suites to compare (default: every suite in both runs)")
    parser.add_argument("--left-setup", action="append", default=[], help="declared left setup key=value")
    parser.add_argument("--right-setup", action="append", default=[], help="declared right setup key=value")
    parser.add_argument("--left-label", help="display name for the left run")
    parser.add_argument("--right-label", help="display name for the right run")
    # view (offline compare shell; --against enables paired-run compare)
    parser.add_argument(
        "--serve",
        action="store_true",
        help="for view: serve the compare bundle on loopback and open a browser",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="for view --serve: loopback port (0 = ephemeral)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="for view --serve: do not open a browser",
    )
    args = parser.parse_args(argv)

    needs_result = args.command in (
        "validate", "report", "import-harbor", "freeze-study",
        "run-study", "export-trace", "judge", "judge-pairwise", "calibrate", "cards",
        "compare-keel-mobile", "view",
    )
    if needs_result and not args.result:
        parser.error(f"{args.command} requires an input path")
    if args.command == "import-harbor" and not args.jobs_root:
        parser.error("import-harbor requires --jobs-root")
    if args.command in ("freeze-study", "export-trace", "init-study", "cards", "view") and not args.out:
        parser.error("this command requires --out")
    if args.command == "view" and args.port < 0:
        parser.error("--port must be >= 0")
    if args.command in ("judge", "judge-pairwise"):
        if not args.rubric or not args.model or not args.base_url:
            parser.error(f"{args.command} requires --rubric, --model, and --base-url")
    if args.command == "compare-keel-mobile":
        if not args.against:
            parser.error("compare-keel-mobile requires --against")
        if args.format not in ("json", "markdown"):
            parser.error("compare-keel-mobile supports --format json or markdown")
    if args.command == "calibrate" and not args.overrides:
        parser.error("calibrate requires --overrides")

    try:
        if args.command == "list-suites":
            from .quickstart import discover_suites
            result = discover_suites()
        elif args.command == "init-study":
            from .quickstart import init_study
            result = init_study(
                contestant_specs=args.contestant,
                out_path=args.out,
                suite=args.suite,
                binary_path=args.binary,
                repetitions=args.repetitions,
                thermal_limit_c=args.thermal_limit,
                probe_edge=args.probe_edge,
            )
        elif args.command == "probe-edge":
            from .edge import detect_hardware, probe_server
            if args.base_url:
                if not args.model:
                    parser.error("probe-edge with --base-url requires --model")
                streams = [int(s.strip()) for s in args.streams.split(",") if s.strip()]
                api_key = os.environ.get(args.api_key_env) if args.api_key_env else None
                result = probe_server(args.base_url, args.model, api_key=api_key, streams=streams)
            else:
                result = {"schema_version": 1, "hardware": detect_hardware()}
            if args.out:
                _write_json_out(args.out, result)
        elif args.command == "judge":
            from .judge import judge_submissions
            submissions = _read_bounded_json(args.result)
            rubric = _read_bounded_json(args.rubric)
            result = judge_submissions(
                submissions,
                rubric,
                judge_model=args.model,
                base_url=args.base_url,
                api_key_env=args.api_key_env,
                seed=args.seed,
            )
            if args.out:
                _write_json_out(args.out, result)
        elif args.command == "judge-pairwise":
            from .judge import judge_pairwise
            submissions = _read_bounded_json(args.result)
            rubric = _read_bounded_json(args.rubric)
            result = judge_pairwise(
                submissions,
                rubric,
                judge_model=args.model,
                base_url=args.base_url,
                api_key_env=args.api_key_env,
                seed=args.seed,
            )
            if args.out:
                _write_json_out(args.out, result)
        elif args.command == "calibrate":
            from .judge import calibrate_judgments
            ledger = _read_bounded_json(args.result)
            overrides = _read_bounded_json(args.overrides)
            results_doc = load(args.results) if args.results else None
            result = calibrate_judgments(ledger, overrides, results_doc=results_doc)
            if args.out:
                _write_json_out(args.out, result)
        elif args.command == "cards":
            from .cards import write_cards
            data = load(args.result)
            summary = summarize(data, pass_k=[int(k) for k in args.pass_k.split(",")])
            result = write_cards(summary, args.out)
        elif args.command == "view":
            from .compare_viewer import (
                serve_compare_bundle,
                write_compare_bundle,
                write_paired_compare_bundle,
            )
            if args.against:
                result = write_paired_compare_bundle(
                    args.result,
                    args.against,
                    args.out,
                    left_label=args.left_label,
                    right_label=args.right_label,
                    left_setup=args.left_setup,
                    right_setup=args.right_setup,
                    suites=args.suites,
                )
            else:
                result = write_compare_bundle(args.result, args.out)
            if args.serve:
                server, url, _thread = serve_compare_bundle(
                    args.out,
                    port=args.port,
                    open_browser=not args.no_open,
                )
                result = {**result, "url": url, "serving": True}
                print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
                print(f"Serving compare view at {url} (Ctrl+C to stop)", file=sys.stderr)
                try:
                    threading.Event().wait()
                except KeyboardInterrupt:
                    pass
                finally:
                    server.shutdown()
                return 0
        elif args.command == "compare-keel-mobile":
            from .keel_mobile import compare_runs, load_run, parse_setup_pairs
            left = load_run(args.result, parse_setup_pairs(args.left_setup), args.left_label)
            right = load_run(args.against, parse_setup_pairs(args.right_setup), args.right_label)
            if left["label"] == right["label"]:
                left["label"], right["label"] = left["label"] + " (left)", right["label"] + " (right)"
            suites = [s.strip() for s in args.suites.split(",") if s.strip()] if args.suites else None
            result = compare_runs(left, right, suites=suites)
        elif args.command == "export-trace":
            from .trajectories import export_trajectory
            result = export_trajectory(args.result, args.out)
        elif args.command == "freeze-study":
            from .study import freeze, read_document
            result = freeze(read_document(args.result), args.out)
        elif args.command == "run-study":
            import asyncio
            from .study import execute
            result = asyncio.run(execute(args.result, resume=args.resume))
        elif args.command == "import-harbor":
            result = import_trials(_read_bounded_json(args.result), args.jobs_root)
        else:
            data = load(args.result)
            result = (
                summarize(data, pass_k=[int(k) for k in args.pass_k.split(",")])
                if args.command == "report"
                else {"valid": True, "purpose": data["purpose"], "attempts": len(data["attempts"])}
            )
    except Exception as error:
        # Inputs can contain private data: do not echo values or file paths.
        if args.command == "compare-keel-mobile" and isinstance(error, InvalidResult):
            # These messages are fixed strings that never include input values.
            print(f"keel-arena: {error}", file=sys.stderr)
        else:
            print(f"keel-arena: invalid or unreadable result ({type(error).__name__})", file=sys.stderr)
        return 2

    if args.command == "compare-keel-mobile" and args.format == "markdown":
        from .keel_mobile import markdown as mobile_markdown
        text = mobile_markdown(result)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
        else:
            print(text, end="")
    elif args.command == "compare-keel-mobile" and args.out:
        _write_json_out(args.out, result)
    elif args.command == "report" and args.format == "markdown":
        from .reporting import markdown
        print(markdown(result), end="")
    elif args.command == "report" and args.format == "svg":
        from .cards import render_overview_svg
        print(render_overview_svg(result))
    elif args.command == "report" and args.format == "html":
        from .cards import render_dashboard_html
        print(render_dashboard_html(result), end="")
    else:
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 3 if args.command == "run-study" and result.get("status") == "thermal_stop" else 0


if __name__ == "__main__":
    raise SystemExit(main())
