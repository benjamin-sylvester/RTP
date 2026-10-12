"""Daily 6:30am job for Railway cron: refresh UW-model figures, regenerate the tracker
workbook, then send the exceptions-only note (or the full briefing if BRIEFING_FULL=1).
Every step records a job_runs row.
  python scripts/daily_job.py            run everything, send the note if anything needs Ben
  python scripts/daily_job.py --dry      sync (dry) + render a preview, send nothing
"""
import json
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))          # so `import sync_uw` (a sibling script) resolves
import os

from _conn import connect
from ingest import briefing, exceptions_note, gmail_client as gc

DRY = "--dry" in sys.argv
ROOT = HERE.parent


def job(conn, name):
    """Context manager-ish helper: returns (run_id, finish) where finish(status, counts, msg)."""
    rid = conn.execute("INSERT INTO job_runs (job) VALUES (%s) RETURNING id", (name,)).fetchone()[0]
    conn.commit()

    def finish(status="ok", counts=None, message=None):
        conn.execute("UPDATE job_runs SET finished_at=now(), status=%s, counts=%s::jsonb, message=%s WHERE id=%s",
                     (status, json.dumps(counts or {}, default=str), message, rid))
        conn.commit()
    return finish


def main():
    with connect(autocommit=False) as conn:
        finish_daily = job(conn, "daily_job")

        # 1) UW model sync. Non-fatal.
        finish = job(conn, "uw_sync")
        try:
            import sync_uw
            res = sync_uw.run_sync(mode="drive", dry=DRY)
            finish("ok", res if isinstance(res, dict) else {"result": str(res)[:200]})
        except Exception as e:
            print(f"[daily] uw-sync error (non-fatal): {type(e).__name__}: {e}")
            finish("error", None, f"{type(e).__name__}: {e}"[:500])

        # 2) tracker workbook from the database (only where the Drive is mounted, i.e. locally)
        if os.environ.get("TRACKER_EXPORT", "").lower() in ("1", "true"):
            try:
                import export_tracker
                export_tracker.main()
            except Exception as e:
                print(f"[daily] tracker export error (non-fatal): {e}")

        # 3) the note
        svc = None if DRY else gc.service()
        if os.environ.get("BRIEFING_FULL", "").lower() in ("1", "true"):
            res = briefing.run(conn, svc=svc, send=not DRY,
                               preview_path=None if not DRY else str(ROOT / "briefing_preview.html"))
            print(f"[daily] briefing: {res['counts']}" + (f" SENT id={res['sent_id']}" if res["sent_id"] else " (not sent)"))
            finish_daily("ok", {"mode": "full_briefing", "sent": bool(res["sent_id"])})
        else:
            res = exceptions_note.run(conn, svc=svc, send=not DRY,
                                      preview_path=None if not DRY else str(ROOT / "briefing_preview.html"))
            print(f"[daily] exceptions note: {res['subject']} | attention={res['attention']}"
                  + (f" SENT id={res['sent_id']}" if res["sent_id"] else " (nothing sent)"))
            finish_daily("ok", {"mode": "exceptions", "attention": res["attention"], "sent": bool(res["sent_id"]), **res["counts"]})


if __name__ == "__main__":
    main()
