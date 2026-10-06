"""Apply one db/migrations/NNN_*.sql file to the live DB (migrations are idempotent).
  python scripts/apply_migration.py 013
"""
import sys
from _conn import connect, ROOT


def main():
    n = sys.argv[1]
    files = sorted((ROOT / "db" / "migrations").glob(f"{n}_*.sql"))
    assert len(files) == 1, f"expected one migration file for {n}, got {files}"
    sql = files[0].read_text(encoding="utf-8")
    with connect(autocommit=True) as conn:
        conn.execute(sql)
    print("applied", files[0].name)


if __name__ == "__main__":
    main()
