"""Buy-box re-route after the 2026-10-12 change (2 to 50 units, NH corridors only; MA = comps).

Two moves, both limited to SYSTEM-managed statuses (comp_only <-> lead). Manual statuses
(underwriting, loi_sent, under_contract, passed, lost, owned) are never touched.

  1. NH comp_only rows that now route to 'lead' and were seen in the last
     pipeline.active_lead_days days -> lead. Older qualifying rows are LISTED but left as
     comp_only so a year of stale listings does not flood the Deals tab.
  2. MA rows sitting at 'lead' -> comp_only (MA is no longer lead-eligible).

Dry-run by default (transaction rolled back). Pass --commit to persist.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect
from ingest import routing, freshness

REASON = "2026-10-12 buy box: 2-50u NH corridors, MA comps only"


def main(commit):
    days = routing.buy_box()["pipeline"]["active_lead_days"]
    conn = connect(autocommit=False)
    try:
        print(f"=== 1. NH comp_only -> lead (seen within {days}d) ===")
        rows = conn.execute(
            "SELECT id, address, city, state, units, asking_price, last_seen_at "
            "FROM listings WHERE state='NH' AND status='comp_only' AND package_id IS NULL "
            "ORDER BY last_seen_at DESC NULLS LAST, id").fetchall()
        promoted, stale_fit, stayed = [], [], 0
        for lid, addr, city, st, units, ask, seen in rows:
            status, reasons = routing.route(st, city, units, ask / 100 if ask else None)
            if status != "lead":
                stayed += 1
                continue
            fresh = conn.execute(
                "SELECT last_seen_at >= NOW() - (%s || ' days')::interval FROM listings WHERE id=%s",
                (str(days), lid)).fetchone()[0]
            line = f"#{lid} {addr}, {city} ({units}u, ${(ask or 0)/100:,.0f}, seen {seen:%Y-%m-%d})" if seen else f"#{lid} {addr}, {city} ({units}u)"
            if fresh:
                freshness.set_status(conn, "listing", lid, "lead", reason=REASON + ": " + reasons[0])
                promoted.append(lid)
                print("  promote ->lead  " + line)
            else:
                stale_fit.append(lid)
                print("  fits, stale     " + line)
        print(f"  promoted {len(promoted)}, fits-but-stale {len(stale_fit)} (left comp_only), stayed {stayed}")

        print("\n=== 2. MA lead -> comp_only ===")
        rows = conn.execute(
            "SELECT id, address, city, units, asking_price FROM listings "
            "WHERE state='MA' AND status='lead' ORDER BY id").fetchall()
        for lid, addr, city, units, ask in rows:
            freshness.set_status(conn, "listing", lid, "comp_only", reason=REASON)
            print(f"  demote ->comp  #{lid} {addr}, {city} ({units}u, ${(ask or 0)/100:,.0f})")
        print(f"  demoted {len(rows)}")

        if commit:
            conn.commit()
            print("\nCOMMITTED.")
        else:
            conn.rollback()
            print("\nDRY-RUN, rolled back. Re-run with --commit to persist.")
    finally:
        conn.close()


if __name__ == "__main__":
    main(commit="--commit" in sys.argv)
