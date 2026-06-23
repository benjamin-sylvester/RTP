"""Pipeline freshness sweep (runs daily before the briefing).
  sweep.py                 dry-run: show which leads WOULD demote (rolls back)
  sweep.py --commit        demote stale leads -> 'stale'
  sweep.py --reactivate ID bring a stale deal back to 'lead'   <-- the one-liner
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect
from ingest import freshness

COMMIT = "--commit" in sys.argv


def main():
    if "--reactivate" in sys.argv:
        lid = int(sys.argv[sys.argv.index("--reactivate") + 1])
        with connect(autocommit=False) as conn:
            row = freshness.reactivate(conn, lid)
            conn.commit()
            print(f"reactivated #{row[0]} {row[1]}, {row[2]} -> lead" if row
                  else f"#{lid} not found or not stale")
        return

    with connect(autocommit=False) as conn:
        demoted = freshness.sweep(conn)
        print(f"active_lead_days = {freshness.active_lead_days()}")
        print(f"deals demoted -> stale: {len(demoted)}")
        for d in demoted:
            print(f"  [{d['kind']}] #{d['id']} {(d['name'] or '?')[:26]:<27}"
                  f"{(d['market'] or ''):<12} last_seen {d['last_seen']:%Y-%m-%d}")
        still_l = conn.execute("SELECT count(*) FROM listings WHERE status='lead'").fetchone()[0]
        still_p = conn.execute("SELECT count(*) FROM packages WHERE status='lead'").fetchone()[0]
        print(f"leads still active: {still_l} listings + {still_p} packages")
        if COMMIT:
            conn.commit(); print("COMMITTED.")
        else:
            conn.rollback(); print("(dry-run; --commit to apply)")


if __name__ == "__main__":
    main()
