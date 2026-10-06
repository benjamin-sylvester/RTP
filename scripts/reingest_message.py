"""Re-run ingestion for specific Gmail message id(s), ignoring the RTP/Ingested label.
Use after a parser upgrade to re-read a message the old code mishandled (e.g. a closing
announcement parsed as a listing before sold-comp support existed).
  python scripts/reingest_message.py <account_key> <msg_id> [<msg_id> ...] [--dry]
account_key: 'personal' or 'rtp' (see gmail_client.accounts()). --dry rolls back + not marked processed.
"""
import pathlib
import sys

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ingest import gmail_client as gc, pipeline, dedup, runner  # noqa: E402


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    key, ids = args[0], args[1:]
    acct = next(a for a in gc.accounts() if a["key"] == key)
    svc = gc.service(acct["refresh_token"])
    session = requests.Session()
    conn = runner._connect()
    try:
        for mid in ids:
            msg = gc.get_message(svc, mid)
            bkey, path, cands = pipeline.extract_candidates(
                svc, msg, session, allow_unknown=True)
            print(f"[{mid}] {msg['subject'][:70]!r} path={path} candidates={len(cands)}")
            for c in cands:
                res = dedup.upsert(conn, c, source=pipeline.source_for(path),
                                   raw_email_id=c.get("_thread_id"),
                                   session=session, account=key)
                keys = ("address", "city", "units", "asking_price", "sale_price",
                        "sale_date", "listing_status", "cap_rate", "other_addresses")
                print("   ", {k: c.get(k) for k in keys if c.get(k) is not None}, "->", res)
            if dry:
                conn.rollback()
            else:
                conn.commit()
                runner.mark_processed(conn, key, mid, "reingest")
                conn.commit()
        print("dry-run: rolled back, not labeled" if dry else "committed + labeled")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
