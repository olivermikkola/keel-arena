"""Offline reporting and explicitly invoked private Harbor studies."""

import argparse
import json
import sys

from .results import InvalidResult, load, summarize
from .harbor_import import import_trials, read_json


def main(argv=None):
    parser = argparse.ArgumentParser(prog="keel-arena")
    parser.add_argument("command", choices=("validate", "report", "import-harbor", "freeze-study", "run-study", "export-trace"))
    parser.add_argument("result", help="path to a normalized v1 result JSON file")
    parser.add_argument("--jobs-root", help="local Harbor jobs directory for import-harbor")
    parser.add_argument("--out", help="new private directory for freeze-study")
    parser.add_argument("--resume", action="store_true", help="resume verified cells in run-study")
    args = parser.parse_args(argv)
    if args.command == "import-harbor" and not args.jobs_root:
        parser.error("import-harbor requires --jobs-root")
    if args.command in ("freeze-study", "export-trace") and not args.out:
        parser.error("this command requires --out")
    try:
        if args.command == "export-trace":
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
            from pathlib import Path
            with Path(args.result).open("rb") as source:
                raw = source.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise InvalidResult("manifest exceeds 16 MiB")
            result = import_trials(read_json(raw), args.jobs_root)
        else:
            data = load(args.result)
            result = summarize(data) if args.command == "report" else {
                "valid": True, "purpose": data["purpose"], "attempts": len(data["attempts"])
            }
    except Exception as error:
        # Inputs can contain private data: do not echo values or file paths.
        print(f"keel-arena: invalid or unreadable result ({type(error).__name__})", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 3 if args.command == "run-study" and result.get("status") == "thermal_stop" else 0


if __name__ == "__main__":
    raise SystemExit(main())
