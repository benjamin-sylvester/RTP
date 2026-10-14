"""Production ingestion runner (for the 15-min cron).
Scans every configured inbox (gc.accounts()), upserts each new message's listings via
the pipeline, then records the message id in `processed_messages` so it is never
reprocessed. Per-message commit keeps each message atomic and the loop forward-only
(idempotent: re-seeing a message at its current price logs nothing).

Processed tracking lives in the DB (migration 014), NOT as a Gmail label: Ben does not
want ingestion to touch or label anything in either inbox. Gmail is read-only here.
"""
import os

import psycopg
import requests

from ingest import gmail_client as gc, pipeline, dedup

# Don't reach back past the verified backfill window.
AFTER_FLOOR = os.environ.get("INGEST_AFTER_FLOOR", "2026/03/24")
# Default scan for any inbox without an explicit GMAIL_SCAN[_KEY]: all mail (inbox AND
# archived, since Superhuman auto-archives broker blasts) from the last 30 days.
DEFAULT_SCAN = os.environ.get("GMAIL_SCAN_DEFAULT",
                              "newer_than:30d -in:sent -in:draft -in:spam -in:trash")
DEAL_FLOW_LABEL = os.environ.get("GMAIL_DEAL_FLOW_LABEL", "Deal Flow")


def _connect():
    gc._load_env()
    return psycopg.connect(os.environ["DATABASE_URL"])


def processed_ids(conn, account):
    return {r[0] for r in conn.execute(
        "SELECT msg_id FROM processed_messages WHERE account=%s", (account,)).fetchall()}


def mark_processed(conn, account, msg_id, result=None):
    conn.execute(
        "INSERT INTO processed_messages (account, msg_id, result) VALUES (%s,%s,%s) "
        "ON CONFLICT (account, msg_id) DO UPDATE SET result=EXCLUDED.result, "
        "processed_at=NOW()", (account, msg_id, result))


def unprocessed_ids(svc, conn, account, after=AFTER_FLOOR, scan_query=None):
    """Candidate message ids not yet in processed_messages, oldest-first.
    scan_query: Gmail search for the inbox (default DEFAULT_SCAN). The literal value
    'label' means the legacy Deal Flow label mode."""
    q = scan_query or DEFAULT_SCAN
    if q == "label":
        src = gc.list_message_ids(svc, DEAL_FLOW_LABEL, after=after)
    else:
        src = gc.list_message_ids_query(svc, q, after=after)
    done = processed_ids(conn, account)
    return list(reversed([m for m in src if m not in done]))  # oldest-first


def run_once(commit=True, after=AFTER_FLOOR, log=print):
    """Process unprocessed messages across EVERY configured inbox (gc.accounts()).
    Deals from all inboxes flow into the one shared DB; dedup collapses the overlap.
    Returns a combined summary dict.

    Per-account: reply-to-kill runs only on the primary inbox (the briefing is
    sent from there, so replies round-trip there); engagement runs on each inbox
    (each scans its own sent mail and matches its own ingested threads)."""
    accts = gc.accounts()
    session = requests.Session()
    s = {"messages": 0, "listings": 0, "inserted": 0, "enriched": 0,
         "linked_package": 0, "needs_review": 0, "no_listing": 0, "sold": 0,
         "errors": 0}
    log(f"[ingest] {len(accts)} inbox(es): " +
        ", ".join(f"{a['key']}({a['email'] or '?'})" for a in accts))
    conn = _connect()
    run_id = None
    if commit:
        try:
            run_id = conn.execute("INSERT INTO job_runs (job) VALUES ('ingest') RETURNING id").fetchone()[0]
            conn.commit()
        except Exception as e:  # job_runs arrives with migration 018; never block ingest on it
            conn.rollback(); log(f"[ingest] job_runs unavailable: {e}")
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
            scan_query = acct.get("scan_query") or DEFAULT_SCAN
            ids = unprocessed_ids(svc, conn, tag, after, scan_query=scan_query)
            log(f"[ingest:{tag}] {len(ids)} unprocessed message(s) after {after} — "
                f"scan ({scan_query})")
            for mid in ids:
                # Isolate each message: a single malformed extraction (common when
                # scanning a general inbox) must not crash the run or block the
                # messages behind it. On error, roll back just this message, mark it
                # processed so it is not retried forever, and continue.
                try:
                    msg = gc.get_message(svc, mid)
                    bkey, path, cands = pipeline.extract_candidates(
                        svc, msg, session, allow_unknown=True)
                    s["messages"] += 1
                    if not cands:
                        s["no_listing"] += 1
                    actions = []
                    for c in cands:
                        res = dedup.upsert(conn, c, source=pipeline.source_for(path),
                                           raw_email_id=c.get("_thread_id"),
                                           session=session, account=tag)
                        s["listings"] += 1
                        s[res["action"]] = s.get(res["action"], 0) + 1
                        if res.get("status") == "needs_review":
                            s["needs_review"] += 1
                        if c.get("_sold"):
                            s["sold"] += 1
                        actions.append(f"{res['action']}:{res.get('listing_id')}")
                    if commit:
                        mark_processed(conn, tag, mid,
                                       (path or "skip") + ("|" + ",".join(actions) if actions else ""))
                        conn.commit()
                    else:
                        conn.rollback()
                except Exception as e:
                    conn.rollback()
                    s["errors"] += 1
                    log(f"[ingest:{tag}] ERROR on msg {mid}: {type(e).__name__}: {e}")
                    msg_l = str(e).lower()
                    if any(k in msg_l for k in ("credit balance", "rate_limit", "overloaded", "not supported for this model",
                                                "thinking", "invalid model", "not_found_error")):
                        # our side (no API credits / throttled): leave the message unprocessed so
                        # it is retried next cycle, and stop burning the rest of the batch
                        s["api_blocked"] = True
                        log(f"[ingest:{tag}] API unavailable; leaving {mid} and the rest of this batch for the next cycle")
                        break
                    if commit:
                        try:
                            mark_processed(conn, tag, mid, f"error:{type(e).__name__}")
                            conn.commit()  # don't reprocess a poison msg
                        except Exception:
                            conn.rollback()
        log(f"[ingest] done: {s}")
        if run_id:
            try:
                import json
                conn.execute("UPDATE job_runs SET finished_at=now(), status=%s, counts=%s::jsonb, message=%s WHERE id=%s",
                             ("error" if s.get("api_blocked") else "warn" if s["errors"] else "ok", json.dumps(s),
                              "Anthropic API unavailable (credits or rate limit); messages left for retry" if s.get("api_blocked") else None, run_id))
                conn.commit()
            except Exception as e:
                conn.rollback(); log(f"[ingest] job_runs update failed: {e}")
        return s
    finally:
        conn.close()


def baseline(after=AFTER_FLOOR, log=print):
    """One-time: mark every currently-matching message processed WITHOUT parsing,
    so the cron starts clean from here (e.g. when first enabling an inbox and the
    backlog is not wanted)."""
    conn = _connect()
    n = 0
    try:
        for acct in gc.accounts():
            svc = gc.service(acct["refresh_token"])
            ids = unprocessed_ids(svc, conn, acct["key"], after,
                                  scan_query=acct.get("scan_query") or DEFAULT_SCAN)
            for mid in ids:
                mark_processed(conn, acct["key"], mid, "baseline")
            conn.commit()
            n += len(ids)
            log(f"[ingest:{acct['key']}] baseline-marked {len(ids)} message(s) processed")
    finally:
        conn.close()
    return n
