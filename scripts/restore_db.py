"""Restore a scripts/backup_db.py backup folder into an EMPTY Postgres (no psql needed).

  .venv\\Scripts\\python.exe scripts\\restore_db.py <backup_dir> <target DATABASE_URL>

Refuses to run if the target already has a listings table (so it can never overwrite
production by accident). Order and method follow RESTORE.txt in the backup folder.
"""
import pathlib
import re
import sys

import psycopg

ORDER = ["broker_format_config", "packages", "system_meta", "listings", "listing_financials",
         "unit_mix", "auto_underwriting", "rent_comps", "listing_history", "processed_messages"]


def main(backup_dir, url):
    b = pathlib.Path(backup_dir)
    wipe = "--wipe" in sys.argv
    with psycopg.connect(url, autocommit=True) as conn:
        exists = conn.execute("SELECT to_regclass('public.listings')").fetchone()[0]
        if exists and wipe:
            import os
            from _conn import load_env
            load_env()
            if url == os.environ.get("DATABASE_URL"):
                sys.exit("--wipe refused: target is the production DATABASE_URL")
            conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            print("wiped target schema (sandbox)")
        elif exists:
            sys.exit("target already has a listings table; refusing to restore over it (use --wipe for the sandbox)")
        print("schema.sql"); conn.execute(b.joinpath("schema.sql").read_text(encoding="utf8"))
        for m in sorted(b.joinpath("migrations").glob("*.sql")):
            print("migration", m.name)
            try:
                conn.execute(m.read_text(encoding="utf8"))
            except Exception as e:  # schema.sql may already include later objects
                print("   skipped:", str(e).splitlines()[0][:120])
        for t in ORDER:
            f = b / f"{t}.csv"
            if not f.exists():
                print("no csv for", t); continue
            header = f.open("r", encoding="utf8").readline().strip()
            cols = ", ".join(c.strip() for c in header.split(","))
            with conn.cursor() as cur, f.open("rb") as fh, cur.copy(
                    f"COPY {t} ({cols}) FROM STDIN WITH (FORMAT csv, HEADER true)") as cp:
                while chunk := fh.read(1 << 16):
                    cp.write(chunk)
            n = conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            print(f"{t:22} {n} rows")
        # bump serial sequences past the restored ids
        for t in ORDER:
            has_id = conn.execute("SELECT 1 FROM information_schema.columns WHERE table_name=%s AND column_name='id'", (t,)).fetchone()
            seq = conn.execute("SELECT pg_get_serial_sequence(%s, 'id')", (t,)).fetchone()[0] if has_id else None
            if seq:
                conn.execute(f"SELECT setval(%s, COALESCE((SELECT MAX(id) FROM {t}), 1))", (seq,))
        print("DONE")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
