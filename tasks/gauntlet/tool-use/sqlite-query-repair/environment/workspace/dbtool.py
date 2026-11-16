import argparse, json, sqlite3
from pathlib import Path

def ensure_db(db_path):
    if db_path.exists():
        return
    seed = json.loads(Path(__file__).with_name("seed.json").read_text())
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE items (sku TEXT PRIMARY KEY, category TEXT, unit_cents INTEGER)")
    con.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, sku TEXT, qty INTEGER, status TEXT)")
    con.executemany("INSERT INTO items VALUES (:sku, :category, :unit_cents)", seed["items"])
    con.executemany("INSERT INTO orders VALUES (:id, :sku, :qty, :status)", seed["orders"])
    con.commit()
    con.close()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sql", required=True)
    p.add_argument("--format", required=True)
    args = p.parse_args()
    if args.format != "json":
        raise SystemExit("ERR: --format must be 'json'")
    if not args.sql.strip().startswith("SELECT "):
        raise SystemExit("ERR: --sql must start with uppercase 'SELECT '")
    db = Path(__file__).with_name("inventory.db")
    ensure_db(db)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(args.sql).fetchall()
    print(json.dumps({"rows": rows}))

if __name__ == "__main__":
    main()
