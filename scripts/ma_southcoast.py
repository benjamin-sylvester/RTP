"""MA SouthCoast rollout (2026-06-29). Two real changes, in order:

  1. Group 282 Sprague St (Fall River) + 49 Nelson St (New Bedford) into ONE package
     from Lyndsey Pachon and set it to 'underwriting' (Ben toured both, requested P&Ls,
     offer imminent). Logged to listing_history.
  2. Re-run buy-box routing over MA standalone comps and promote the ones that now qualify
     (SouthCoast corridor: Fall River / New Bedford) from comp_only -> lead. Logged too.

The package is created FIRST so its member parcels carry a package_id and are skipped by
the re-route (a package member is never promoted as a standalone lead).

Safety (memory: testing-against-live-db): dry-run by default — runs inside a transaction and
ROLLS BACK unless --commit is passed. Sticky statuses are never touched (only comp_only is
re-routed; manual/terminal statuses are left alone)."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect
from ingest import routing, freshness

PKG_NAME = "282 Sprague St + 49 Nelson St (SouthCoast 12-unit pkg)"
PKG_BROKER = ("Lyndsey Pachon", "lpachon@fallriverpm.com")  # Fall River Property Management
MEMBER_IDS = (319, 320)
PKG_REASON = "Ben toured both, requested P&Ls, offer imminent"


def make_package(conn, log=print):
    """Create the Sprague+Nelson package (idempotent by name), link the two parcels,
    set it to underwriting via freshness.set_status (logs history)."""
    row = conn.execute("SELECT id, status FROM packages WHERE name=%s", (PKG_NAME,)).fetchone()
    if row:
        pid, status = row
        log(f"  package exists: #{pid} ({status})")
    else:
        # roll the package ask up from the two member asks for a clean package-level number
        ask, units = conn.execute(
            "SELECT SUM(asking_price), SUM(units) FROM listings WHERE id = ANY(%s)",
            (list(MEMBER_IDS),)).fetchone()
        pid = conn.execute(
            """INSERT INTO packages
                 (name, market, state, status, total_units, asking_price,
                  broker_name, broker_email, last_seen_at, notes)
               VALUES (%s, 'Fall River / New Bedford', 'MA', 'comp_only', %s, %s,
                       %s, %s, NOW(), %s)
               RETURNING id""",
            (PKG_NAME, units, ask, PKG_BROKER[0], PKG_BROKER[1],
             f"SouthCoast 2-property package from {PKG_BROKER[0]} ({PKG_BROKER[1]}).")
        ).fetchone()[0]
        log(f"  created package #{pid}: {PKG_NAME}  ({units}u, ${ask/100:,.0f})")

    n = conn.execute(
        "UPDATE listings SET package_id=%s WHERE id = ANY(%s) AND package_id IS DISTINCT FROM %s",
        (pid, list(MEMBER_IDS), pid)).rowcount
    log(f"  linked {n} parcel(s) -> package #{pid}")

    res = freshness.set_status(conn, "package", pid, "underwriting", reason=PKG_REASON)
    if res:
        log(f"  status: package #{pid} {res['old']} -> {res['new']}")
    return pid


def reroute_ma(conn, log=print):
    """Re-evaluate MA standalone comp_only listings; promote qualifying ones to lead."""
    rows = conn.execute(
        "SELECT id, address, city, state, units, asking_price FROM listings "
        "WHERE state='MA' AND status='comp_only' AND package_id IS NULL ORDER BY id"
    ).fetchall()
    promoted, stayed = [], 0
    for lid, addr, city, state, units, ask in rows:
        status, reasons = routing.route(state, city, units, ask / 100 if ask else None)
        if status == "lead":
            freshness.set_status(conn, "listing", lid, "lead",
                                 reason="MA SouthCoast re-route: " + reasons[0])
            promoted.append((lid, addr, city, units, ask))
            log(f"  promote #{lid} {addr}, {city} ({units}u, ${ask/100:,.0f}) -> lead")
        else:
            stayed += 1
    log(f"  re-route: {len(promoted)} promoted to lead, {stayed} stayed comp_only")
    return promoted


def main(commit):
    conn = connect(autocommit=False)
    try:
        print("=== 1. Sprague + Nelson package ===")
        make_package(conn, log=print)
        print("\n=== 2. Re-route MA comps ===")
        reroute_ma(conn, log=print)

        if commit:
            conn.commit()
            print("\nCOMMITTED.")
        else:
            conn.rollback()
            print("\nDRY-RUN — rolled back. Re-run with --commit to persist.")
    finally:
        conn.close()


if __name__ == "__main__":
    main(commit="--commit" in sys.argv)
