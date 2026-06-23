"""Pipeline freshness sweep — demote stale leads so the active pipeline stays real.
A 'lead' not seen within buy_box.yaml pipeline.active_lead_days auto-demotes to 'stale'
(stays in the DB as a comp; v_pipeline / v_pipeline_deals already exclude it).
'underwriting' and 'under_contract' are never touched. Reactivate manually anytime.
Runs before the daily briefing."""
from ingest import routing


def active_lead_days():
    return routing.buy_box()["pipeline"]["active_lead_days"]


def sweep(conn):
    """Demote stale leads (listings AND packages) -> 'stale' past active_lead_days.
    Packages are as fresh as their most recent member. underwriting/under_contract are
    never touched. Logs listing status changes to listing_history. Returns demoted rows
    as dicts: {kind, id, name, market, last_seen}."""
    days = active_lead_days()
    cutoff = f"NOW() - make_interval(days => {int(days)})"

    # keep package freshness current = max(member last_seen_at)
    conn.execute("UPDATE packages p SET last_seen_at = "
                 "(SELECT max(l.last_seen_at) FROM listings l WHERE l.package_id = p.id)")

    out = []
    for lid, addr, city, seen in conn.execute(
        f"UPDATE listings SET status='stale' WHERE status='lead' AND last_seen_at < {cutoff} "
        f"RETURNING id, address, city, last_seen_at").fetchall():
        conn.execute(
            "INSERT INTO listing_history (listing_id, field, old_value, new_value) "
            "VALUES (%s, 'status', 'lead', 'stale')", (lid,))
        out.append({"kind": "listing", "id": lid, "name": addr, "market": city, "last_seen": seen})

    for pid, name, market, seen in conn.execute(
        f"UPDATE packages SET status='stale' WHERE status='lead' AND last_seen_at < {cutoff} "
        f"RETURNING id, name, market, last_seen_at").fetchall():
        out.append({"kind": "package", "id": pid, "name": name, "market": market, "last_seen": seen})
    return out


def kill(conn, listing_id, reason=None):
    """Manually reject a deal you've reviewed and don't like (-> status 'dead').
    Drops out of the pipeline + briefing; stays in the DB as a comp. Logs the change."""
    old = conn.execute("SELECT status FROM listings WHERE id=%s", (listing_id,)).fetchone()
    if not old or old[0] == "dead":
        return None
    conn.execute("UPDATE listings SET status='dead' WHERE id=%s", (listing_id,))
    conn.execute("INSERT INTO listing_history (listing_id, field, old_value, new_value) "
                 "VALUES (%s, 'status', %s, 'dead')", (listing_id, old[0]))
    if reason:
        conn.execute("UPDATE listings SET notes = COALESCE(notes,'') || %s WHERE id=%s",
                     (f" [killed: {reason}]", listing_id))
    return conn.execute("SELECT id, address, city FROM listings WHERE id=%s", (listing_id,)).fetchone()


def reactivate(conn, listing_id):
    """Bring a stale OR killed deal back into the pipeline (-> lead, refresh seen)."""
    old = conn.execute("SELECT status FROM listings WHERE id=%s", (listing_id,)).fetchone()
    if not old or old[0] not in ("stale", "dead"):
        return None
    conn.execute("UPDATE listings SET status='lead', last_seen_at=NOW() WHERE id=%s", (listing_id,))
    conn.execute("INSERT INTO listing_history (listing_id, field, old_value, new_value) "
                 "VALUES (%s, 'status', %s, 'lead')", (listing_id, old[0]))
    return conn.execute("SELECT id, address, city FROM listings WHERE id=%s", (listing_id,)).fetchone()
