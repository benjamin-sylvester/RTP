"""Pipeline freshness sweep — demote stale leads so the active pipeline stays real.
A 'lead' not seen within buy_box.yaml pipeline.active_lead_days auto-demotes to 'stale'
(stays in the DB as a comp; v_pipeline / v_pipeline_deals already exclude it).
'underwriting' and 'under_contract' are never touched. Reactivate manually anytime.
Runs before the daily briefing."""
from ingest import routing


def active_lead_days():
    return routing.buy_box()["pipeline"]["active_lead_days"]


def sweep(conn):
    """Demote lead -> stale where last_seen_at older than active_lead_days. Logs each
    status change to listing_history. Returns the demoted rows."""
    days = active_lead_days()
    rows = conn.execute(
        "UPDATE listings SET status='stale' "
        "WHERE status='lead' AND last_seen_at < NOW() - make_interval(days => %s) "
        "RETURNING id, address, city, last_seen_at", (days,)).fetchall()
    for lid, *_ in rows:
        conn.execute(
            "INSERT INTO listing_history (listing_id, field, old_value, new_value) "
            "VALUES (%s, 'status', 'lead', 'stale')", (lid,))
    return rows


def reactivate(conn, listing_id):
    """Manually bring a stale deal back into the pipeline (stale -> lead, refresh seen)."""
    row = conn.execute(
        "UPDATE listings SET status='lead', last_seen_at=NOW() "
        "WHERE id=%s AND status='stale' RETURNING id, address, city", (listing_id,)
    ).fetchone()
    if row:
        conn.execute(
            "INSERT INTO listing_history (listing_id, field, old_value, new_value) "
            "VALUES (%s, 'status', 'stale', 'lead')", (listing_id,))
    return row
