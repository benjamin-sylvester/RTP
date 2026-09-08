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


def unprocessed_ids(svc, after=AFTER_FLOOR, scan_query=None):
    """Candidate message ids lacking the RTP/Ingested label, oldest-first.
    Default: messages under the Deal Flow label. If scan_query is given, scan all
    mail matching that Gmail query instead (scan-all inbox)."""
    if scan_query:
        src = gc.list_message_ids_query(svc, scan_query, after=after)
    else:
        src = gc.list_message_ids(svc, DEAL_FLOW_LABEL, after=after)
    done = set()
    if gc.label_id(svc, INGESTED_LABEL):
        done = set(gc.list_message_ids(svc, INGESTED_LABEL))
    return list(reversed([m for m in src if m not in done]))  # oldest-first


def label_message(svc, msg_id, label_id):
    svc.users().messages().modify(
        userId="me", id=msg_id, body={"addLabelIds": [label_id]}).execute()


def run_once(commit=True, after=AFTER_FLOOR, do_label=True, log=print):
    """Process unprocessed Deal Flow messages across EVERY configured inbox
    (gc.accounts()). Deals from all inboxes flow into the one shared DB; dedup
    collapses the overlap. Returns a combined summary dict.

    Per-account: reply-to-kill runs only on the primary inbox (the briefing is
    sent from there, so replies round-trip there); engagement runs on each inbox
    (each scans its own sent mail and matches its own ingested threads)."""
    accts = gc.accounts()
    session = requests.Session()
    s = {"messages": 0, "listings": 0, "inserted": 0, "enriched": 0,
         "linked_package": 0, "needs_review": 0, "no_listing": 0, "labeled": 0}
    log(f"[ingest] {len(accts)} inbox(es): " +
        ", ".join(f"{a['key']}({a['email'] or '?'})" for a in accts))
    conn = _connect()
    try:
        for acct in accts:
            svc = gc.service(acct["refresh_token"])
            tag = acct["key"]
            if commit:
                # reply-to-kill: only the primary inbox receives briefing replies
                if acct.get("primary"):
                    try:
                        from ingest import reply_commands
                        reply_commands.process_replies(svc, conn, log=log)
                    except Exception as e:
                        log(f"[reply-cmd:{tag}] error: {e}")
                # engagement auto-promotion: per-inbox (own sent mail, own threads)
                try:
                    from ingest import engagement
                    engagement.run(conn, svc, log=log)
                except Exception as e:
                    log(f"[engage:{tag}] error: {e}")
            ing_label = gc.ensure_label(svc, INGESTED_LABEL)
            scan_query = acct.get("scan_query")
            ids = unprocessed_ids(svc, after, scan_query=scan_query)
            mode = f"scan-all ({scan_query})" if scan_query else f"label '{DEAL_FLOW_LABEL}'"
            log(f"[ingest:{tag}] {len(ids)} unprocessed message(s) after {after} — {mode}")
            for mid in ids:
                msg = gc.get_message(svc, mid)
                bkey, path, cands = pipeline.extract_candidates(
                    svc, msg, session, allow_unknown=bool(scan_query))
                s["messages"] += 1
                if not cands:
                    s["no_listing"] += 1
                for c in cands:
                    res = dedup.upsert(conn, c, source=pipeline.source_for(path),
                                       raw_email_id=c.get("_thread_id"),
                                       session=session, account=tag)
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
