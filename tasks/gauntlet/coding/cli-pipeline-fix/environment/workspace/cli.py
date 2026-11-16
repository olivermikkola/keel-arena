import argparse
import sys
from pathlib import Path
from parser import parse_events
from formatter import format_summary


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("input")
    p.add_argument("--min-duration", type=int, default=None)
    args = p.parse_args(argv)
    events = parse_events(Path(args.input).read_text(encoding="utf-8"))
    print(format_summary(events, min_duration=args.min_duration))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
