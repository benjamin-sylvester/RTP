"""Production ingestion runner (for the 15-min cron).
Processes Deal Flow messages that are NOT yet labeled RTP/Ingested (and newer than
the backfill floor), upserts each via the pipeline, then labels the message so it is
never reprocessed. Per-message commit+label keeps each message atomic and the loop
forward-only (idempotent: re-seeing a message at its current price logs nothing).
"""
import os

import psycopg
import requests

from ingest import gmail_client as gc, pipeline, dedup

INGESTED_LABEL = "RTP/Ingested"
DEAL_FLOW_LABEL = os.environ.get("GMAIL_DEAL_FLOW_LABEL", "Deal Flow")
# Don't reach back past the verified backfill window.
AFTER_FLOOR = os.environ.get("INGEST_AFTER_FLOOR", "2026/03/24")


def _connect():
    gc._load_env()
    return psycopg.connect(os.environ["DATABASE_URL"])


def unprocessed_ids(svc, after=AFTER_FLOOR):
    """Deal Flow messages (after floor) lacking the RTP/Ingested label, oldest-first."""
    df = gc.list_message_ids(svc, DEAL_FLOW_LABEL, after=after)
    done = set()
    if gc.label_id(svc, INGESTED_LABEL):
        done = set(gc.list_message_ids(svc, INGESTED_LABEL))
    return list(reversed([m for m in df if m not in done]))  # oldest-first


def label_message(svc, msg_id, label_id):
    svc.users().messages().modify(
        userId="me", id=msg_id, body={"addLabelIds": [label_id]}).execute()


def run_once(commit=True, after=AFTER_FLOOR, do_label=True, log=print):
    """Process all currently-unprocessed messages. Returns a summary dict."""
    svc = gc.service()
    ing_label = gc.ensure_label(svc, INGESTED_LABEL)
    ids = unprocessed_ids(svc, after)
    session = requests.Session()
    s = {"messages": 0, "listings": 0, "inserted": 0, "enriched": 0,
         "linked_package": 0, "needs_review": 0, "no_listing": 0, "labeled": 0}
    log(f"[ingest] {len(ids)} unprocessed message(s) after {after}")
    conn = _connect()
    try:
        for mid in ids:
            msg = gc.get_message(svc, mid)
            bkey, path, cands = pipeline.extract_candidates(svc, msg, session)
            s["messages"] += 1
            if not cands:
                s["no_listing"] += 1
            for c in cands:
                res = dedup.upsert(conn, c, source=pipeline.source_for(path),
                                   raw_email_id=c.get("_thread_id"), session=session)
                s["listings"] += 1
                s[res["action"]] = s.get(res["action"], 0) + 1
                if res.get("status") == "needs_review":
                    s["needs_review"] += 1
            if commit:
                conn.commit()
                if do_label:
                    label_message(svc, mid, ing_label)
                    s["labeled"] += 1
            else:
                conn.rollback()
        log(f"[ingest] done: {s}")
        return s
    finally:
        conn.close()


def label_baseline(after=AFTER_FLOOR, log=print):
    """One-time: label already-backfilled messages as ingested WITHOUT reprocessing,
    so the cron starts clean and never re-runs them."""
    svc = gc.service()
    ing_label = gc.ensure_label(svc, INGESTED_LABEL)
    ids = unprocessed_ids(svc, after)
    for mid in ids:
        label_message(svc, mid, ing_label)
    log(f"[ingest] baseline-labeled {len(ids)} message(s) as {INGESTED_LABEL}")
    return len(ids)
