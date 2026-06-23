"""Correct listings.last_seen_at to each deal's TRUE source date (migration 005's
backfill used today's ingest/history times, so nothing ages out).

Priority per deal: most recent Gmail internalDate across (a) its raw_email_id thread
AND (b) any Deal Flow message/digest carrying its external_id/MLS# -> then listing_date
-> then date_ingested. Re-runnable (recomputes from Gmail each time)."""
import sys
import pathlib
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect
from ingest import gmail_client as gc, structured

COMMIT = "--commit" in sys.argv


def build_maps(svc):
    """thread_id -> latest internalDate(ms); external_id -> latest internalDate(ms)."""
    thread_latest, ext_latest = {}, {}
    for mid in gc.list_message_ids(svc, "Deal Flow"):
        m = gc.get_message(svc, mid)
        ms, tid = m["internal_date_ms"], m["thread_id"]
        thread_latest[tid] = max(thread_latest.get(tid, 0), ms)
        bkey = gc.match_broker(m["from_email"])
        if structured.can_parse(bkey):
            for r in structured.parse(bkey, m["html"]):
                eid = r.get("external_id")
                if eid:
                    ext_latest[str(eid)] = max(ext_latest.get(str(eid), 0), ms)
    return thread_latest, ext_latest


def main():
    svc = gc.service()
    thread_latest, ext_latest = build_maps(svc)
    print(f"scanned threads={len(thread_latest)}, distinct MLS#s={len(ext_latest)}\n")

    src_counts = {"gmail": 0, "listing_date": 0, "date_ingested": 0}
    with connect(autocommit=False) as conn:
        rows = conn.execute(
            "SELECT id, raw_email_id, external_id, listing_date, date_ingested FROM listings"
        ).fetchall()
        for lid, thread, ext, ldate, ding in rows:
            cands = []
            if thread and thread in thread_latest:
                cands.append(thread_latest[thread])
            if ext and str(ext) in ext_latest:
                cands.append(ext_latest[str(ext)])
            if cands:
                ts = datetime.fromtimestamp(max(cands) / 1000, tz=timezone.utc)
                src = "gmail"
            elif ldate:
                ts = datetime(ldate.year, ldate.month, ldate.day, tzinfo=timezone.utc)
                src = "listing_date"
            else:
                ts = ding
                src = "date_ingested"
            src_counts[src] += 1
            conn.execute("UPDATE listings SET last_seen_at=%s WHERE id=%s", (ts, lid))

        print(f"last_seen_at source: {src_counts}")
        print("\ndistribution of last_seen_at (month):")
        for r in conn.execute(
            "SELECT to_char(last_seen_at,'YYYY-MM') AS mon, count(*), "
            "count(*) FILTER (WHERE status='lead') AS leads "
            "FROM listings GROUP BY mon ORDER BY mon").fetchall():
            print(f"  {r[0]}: {r[1]} listings ({r[2]} leads)")
        if COMMIT:
            conn.commit(); print("\nCOMMITTED.")
        else:
            conn.rollback(); print("\n(dry-run; --commit to apply)")


if __name__ == "__main__":
    main()
