"""Daily 6:30am job for Railway cron: send the briefing.
(No freshness sweep anymore — activeness is by last_seen_at within active_lead_days,
filtered in the briefing query; a quiet lead is just noted, never status-changed.)
  python scripts/daily_job.py            send briefing to DISPATCH_EMAIL
  python scripts/daily_job.py --dry      render preview, no send
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect
from ingest import briefing, gmail_client as gc

DRY = "--dry" in sys.argv
ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    svc = None if DRY else gc.service()
    with connect(autocommit=False) as conn:
        res = briefing.run(conn, svc=svc, send=not DRY,
                           preview_path=None if not DRY else str(ROOT / "briefing_preview.html"))
        print(f"[daily] briefing: {res['counts']}"
              + (f" — SENT id={res['sent_id']}" if res["sent_id"] else " — dry-run (not sent)"))


if __name__ == "__main__":
    main()
