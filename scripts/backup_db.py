"""Pure-Python logical backup of the RTP Postgres. No pg_dump required.

Dumps every base table to a timestamped folder as CSV (exact, via COPY), and
writes a RESTORE.txt with the recipe. Restorable into any Postgres by running
db/schema.sql + migrations, then COPY each CSV back in FK-safe order.

    .venv\\Scripts\\python.exe scripts\\backup_db.py [dest_dir]

Default dest: "G:/Shared drives/RTP G-Drive/6.0 Claude/backups".
Read-only against the database (COPY ... TO STDOUT only).
"""
import csv
import io
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _conn import connect

DEFAULT_DEST = pathlib.Path(
    "G:/Shared drives/RTP G-Drive/6.0 Claude/backups")

# FK-safe order: parents before children. Restore in this order; the file list
# doubles as the COPY sequence.
TABLE_ORDER = [
    "broker_format_config",
    "packages",
    "system_meta",
    "listings",
    "listing_financials",
    "unit_mix",
    "auto_underwriting",
    "rent_comps",
    "listing_history",
]


def main():
    dest_root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DEST
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    dest = dest_root / f"rtp_db_{stamp}"
    dest.mkdir(parents=True, exist_ok=True)

    conn = connect()
    print(f"Backing up to {dest}\n")

    # Confirm every expected table exists; include any extras we don't know about.
    present = {r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_type='BASE TABLE'").fetchall()}
    ordered = [t for t in TABLE_ORDER if t in present]
    extras = sorted(present - set(TABLE_ORDER))
    if extras:
        print(f"note: extra tables not in known order, appended: {extras}")
        ordered += extras

    manifest = []
    total_rows = 0
    for table in ordered:
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        out = dest / f"{table}.csv"
        with open(out, "w", newline="", encoding="utf-8") as fh:
            with conn.cursor().copy(
                f"COPY {table} TO STDOUT WITH (FORMAT csv, HEADER true)") as cp:
                for chunk in cp:
                    fh.write(bytes(chunk).decode("utf-8"))
        size = out.stat().st_size
        manifest.append((table, n, size))
        total_rows += n
        print(f"  {table:<24} {n:>6} rows   {size:>10,} bytes")

    # Copy the DDL alongside the data so the backup is self-contained.
    repo = pathlib.Path(__file__).resolve().parent.parent
    schema_txt = (repo / "db" / "schema.sql").read_text(encoding="utf-8")
    (dest / "schema.sql").write_text(schema_txt, encoding="utf-8")
    mig_dir = repo / "db" / "migrations"
    if mig_dir.exists():
        (dest / "migrations").mkdir(exist_ok=True)
        for m in sorted(mig_dir.glob("*.sql")):
            (dest / "migrations" / m.name).write_text(
                m.read_text(encoding="utf-8"), encoding="utf-8")

    restore = [
        "RTP Postgres logical backup",
        f"Taken: {datetime.now(timezone.utc).isoformat()}",
        f"Tables: {len(manifest)}   Total rows: {total_rows}",
        "",
        "RESTORE into an empty Postgres:",
        "  1. psql $URL -f schema.sql",
        "  2. for m in migrations/*.sql: psql $URL -f $m",
        "  3. For each table below, in THIS order:",
        "       psql $URL -c \"\\copy <table> FROM '<table>.csv' WITH (FORMAT csv, HEADER true)\"",
        "",
        "Table order (FK-safe):",
    ]
    restore += [f"  {t}   ({n} rows)" for t, n, _ in manifest]
    (dest / "RESTORE.txt").write_text("\n".join(restore) + "\n", encoding="utf-8")

    conn.close()
    print(f"\nDONE. {len(manifest)} tables, {total_rows} rows -> {dest}")
    print("Self-contained: CSVs + schema.sql + migrations + RESTORE.txt")


if __name__ == "__main__":
    main()
