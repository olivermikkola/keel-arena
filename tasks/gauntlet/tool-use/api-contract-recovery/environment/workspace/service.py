import argparse, json

ITEMS = [
    {"id": "m-01", "value": 10}, {"id": "m-02", "value": 25}, {"id": "m-03", "value": 15},
    {"id": "m-04", "value": 30}, {"id": "m-05", "value": 5}, {"id": "m-06", "value": 40},
    {"id": "m-07", "value": 12},
]

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cursor", type=int, default=0)
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--token", default="")
    args = p.parse_args()
    if args.token != "edge-ok-2026":
        print(json.dumps({"error": "ERR_AUTH", "hint": "pass --token edge-ok-2026"}))
        raise SystemExit(1)
    if args.limit < 1 or args.limit > 3:
        print(json.dumps({"error": "ERR_LIMIT", "hint": "limit must be between 1 and 3"}))
        raise SystemExit(1)
    chunk = ITEMS[args.cursor:args.cursor + args.limit]
    nxt = args.cursor + args.limit if args.cursor + args.limit < len(ITEMS) else None
    print(json.dumps({"items": chunk, "next_cursor": nxt}))

if __name__ == "__main__":
    main()
