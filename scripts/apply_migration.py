"""Apply one db/migrations/NNN_*.sql file (migrations are idempotent).
  python scripts/apply_migration.py 015            -> production (DATABASE_URL)
  python scripts/apply_migration.py 015 --sandbox  -> SANDBOX_DATABASE_URL (rehearse here first)
"""
import os
import sys

import psycopg
from _conn import connect, ROOT, load_env


def main():
    n = sys.argv[1]
    sandbox = "--sandbox" in sys.argv
    files = sorted((ROOT / "db" / "migrations").glob(f"{n}_*.sql"))
    assert len(files) == 1, f"expected one migration file for {n}, got {files}"
    sql = files[0].read_text(encoding="utf-8")
    if sandbox:
        load_env()
        conn = psycopg.connect(os.environ["SANDBOX_DATABASE_URL"], autocommit=True)
    else:
        conn = connect(autocommit=True)
    with conn:
        conn.execute(sql)
    print("applied", files[0].name, "to", "SANDBOX" if sandbox else "PRODUCTION")


if __name__ == "__main__":
    main()
