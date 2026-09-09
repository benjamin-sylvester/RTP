"""Daily 6:30am job for Railway cron: refresh UW-model figures, then send briefing.
(No freshness sweep anymore — activeness is by last_seen_at within active_lead_days,
filtered in the briefing query; a quiet lead is just noted, never status-changed.)
  python scripts/daily_job.py            sync UW models + send briefing
  python scripts/daily_job.py --dry      sync (dry) + render preview, no send
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))          # so `import sync_uw` (a sibling script) resolves
from _conn import connect
from ingest import briefing, gmail_client as gc

DRY = "--dry" in sys.argv
ROOT = HERE.parent


def main():
    # 1) pull the latest underwriting figures from each active deal's Drive model.
    #    Non-fatal: a sync error must never block the morning briefing.
    try:
        import sync_uw
        sync_uw.run_sync(mode="drive", dry=DRY)
    except Exception as e:
        print(f"[daily] uw-sync error (non-fatal): {type(e).__name__}: {e}")

    # 2) briefing
    svc = None if DRY else gc.service()
    with connect(autocommit=False) as conn:
        res = briefing.run(conn, svc=svc, send=not DRY,
                           preview_path=None if not DRY else str(ROOT / "briefing_preview.html"))
        print(f"[daily] briefing: {res['counts']}"
              + (f" — SENT id={res['sent_id']}" if res["sent_id"] else " — dry-run (not sent)"))


if __name__ == "__main__":
    main()
