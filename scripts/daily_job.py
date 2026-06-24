"""Daily 6:30am job for Railway cron: freshness sweep, THEN send the briefing.
One entrypoint so a single cron service runs both in order.
  python scripts/daily_job.py            sweep + send briefing to DISPATCH_EMAIL
  python scripts/daily_job.py --dry      sweep (rolled back) + render preview, no send
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect
from ingest import freshness, briefing, gmail_client as gc

DRY = "--dry" in sys.argv
ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    with connect(autocommit=False) as conn:
        demoted = freshness.sweep(conn)
        if DRY:
            conn.rollback()
        else:
            conn.commit()
        print(f"[daily] sweep demoted {len(demoted)} deal(s) -> stale")

    svc = None if DRY else gc.service()
    with connect(autocommit=False) as conn:
        res = briefing.run(conn, svc=svc, send=not DRY,
                           preview_path=None if not DRY else str(ROOT / "briefing_preview.html"))
        print(f"[daily] briefing: {res['counts']}"
              + (f" — SENT id={res['sent_id']}" if res["sent_id"] else " — dry-run (not sent)"))


if __name__ == "__main__":
    main()
