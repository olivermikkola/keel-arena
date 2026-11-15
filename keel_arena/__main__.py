"""Read-only CLI; never executes task content or contacts providers."""

import argparse
import json
import sys

from .results import InvalidResult, load, summarize


def main(argv=None):
    parser = argparse.ArgumentParser(prog="keel-arena")
    parser.add_argument("command", choices=("validate", "report"))
    parser.add_argument("result", help="path to a normalized v1 result JSON file")
    args = parser.parse_args(argv)
    try:
        data = load(args.result)
        result = summarize(data) if args.command == "report" else {
            "valid": True, "purpose": data["purpose"], "attempts": len(data["attempts"])
        }
    except (InvalidResult, OSError, ValueError, RecursionError) as error:
        # Inputs can contain private data: do not echo values or file paths.
        print(f"keel-arena: invalid or unreadable result ({type(error).__name__})", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
