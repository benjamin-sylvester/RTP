"""Deal status transitions (STATUS_MODEL.md). No auto lead->stale sweep anymore —
activeness is by last_seen_at within active_lead_days, filtered in the app/views.
Manual status changes are sticky; ingestion never touches them."""
from psycopg.rows import tuple_row

from ingest import routing

ACTIVE_STATUSES = ("lead", "underwriting", "loi_sent", "under_contract")
# statuses a human may set from the dashboard / CLI
MANUAL_TARGETS = ("underwriting", "loi_sent", "under_contract", "lost", "passed", "lead")
VALID = ("comp_only", "lead", "underwriting", "loi_sent", "under_contract",
         "lost", "passed", "needs_review")


def active_lead_days():
    return routing.buy_box()["pipeline"]["active_lead_days"]


def set_status(conn, kind, deal_id, new_status, reason=None):
    """Set a deal's status (listing OR package), logging to listing_history.
    Returns {kind,id,name,old,new} or None if not found."""
    if new_status not in VALID:
        raise ValueError(f"invalid status {new_status!r}")
    cur = conn.cursor(row_factory=tuple_row)  # robust to dict_row connections (the API)
    if kind == "package":
        row = cur.execute("SELECT name, status FROM packages WHERE id=%s", (deal_id,)).fetchone()
        if not row:
            return None
        name, old = row
        cur.execute("UPDATE packages SET status=%s, last_seen_at=CASE WHEN %s='lead' "
                    "THEN NOW() ELSE last_seen_at END WHERE id=%s",
                    (new_status, new_status, deal_id))
        for (mid,) in cur.execute("SELECT id FROM listings WHERE package_id=%s",
                                  (deal_id,)).fetchall():
            cur.execute("INSERT INTO listing_history (listing_id, field, old_value, new_value) "
                        "VALUES (%s, 'package_status', %s, %s)", (mid, old, new_status))
        if reason:
            cur.execute("UPDATE packages SET notes=COALESCE(notes,'')||%s WHERE id=%s",
                        (f" [{new_status}: {reason}]", deal_id))
        return {"kind": "package", "id": deal_id, "name": name, "old": old, "new": new_status}

    row = cur.execute("SELECT address, status FROM listings WHERE id=%s", (deal_id,)).fetchone()
    if not row:
        return None
    name, old = row
    cur.execute("UPDATE listings SET status=%s, last_seen_at=CASE WHEN %s='lead' "
                "THEN NOW() ELSE last_seen_at END WHERE id=%s",
                (new_status, new_status, deal_id))
    cur.execute("INSERT INTO listing_history (listing_id, field, old_value, new_value) "
                "VALUES (%s, 'status', %s, %s)", (deal_id, old, new_status))
    if reason:
        cur.execute("UPDATE listings SET notes=COALESCE(notes,'')||%s WHERE id=%s",
                    (f" [{new_status}: {reason}]", deal_id))
    return {"kind": "listing", "id": deal_id, "name": name, "old": old, "new": new_status}


def kill(conn, listing_id, reason=None):
    """Back-compat alias for 'reviewed and chose not to pursue' -> passed."""
    return set_status(conn, "listing", listing_id, "passed", reason)


def reactivate(conn, deal_id, kind="listing"):
    """Bring a deal back into the pipeline (-> lead, refresh last_seen)."""
    return set_status(conn, kind, deal_id, "lead", None)
