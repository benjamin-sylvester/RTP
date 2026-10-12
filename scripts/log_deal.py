"""Log or update a deal in the listings table from the command line (replaces deal-log.csv).

  --find "16-20 Lafayette" --city Rochester            search existing rows
  --address "16-20 Lafayette St" --city Rochester --state NH --units 3 --price 775000
      [--broker "Justin Porter" --broker-email x@y --notes "..." --source manual --year-built 1911]
                                                       insert (dedups on street number + street + city)
  --id 349 --status loi_sent --reason "LOI sent to Porter 10/8"   set a manual status (logged)
  --id 349 --drive-folder <id> [--boe-url <url>]       set Drive pointers
"""
import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect
from ingest import routing, freshness


def key(addr):
    m = re.match(r"\s*(\d+)[^\s]*\s+(\S+)", addr or "")
    return (m.group(1), m.group(2).lower().rstrip(".,")) if m else (None, None)


def find(conn, addr, city):
    num, street = key(addr)
    if not num:
        return []
    return conn.execute(
        "SELECT id, address, city, state, units, asking_price, status, last_seen_at::date "
        "FROM listings WHERE lower(city)=lower(%s) AND address ILIKE %s ORDER BY id",
        (city, f"{num}%{street}%")).fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--find"); ap.add_argument("--address"); ap.add_argument("--city")
    ap.add_argument("--state", default="NH"); ap.add_argument("--units", type=int)
    ap.add_argument("--price", type=float, help="asking price in dollars")
    ap.add_argument("--broker"); ap.add_argument("--broker-email"); ap.add_argument("--notes")
    ap.add_argument("--source", default="manual"); ap.add_argument("--year-built", type=int)
    ap.add_argument("--id", type=int); ap.add_argument("--status"); ap.add_argument("--reason", default="")
    ap.add_argument("--drive-folder"); ap.add_argument("--boe-url")
    a = ap.parse_args()
    conn = connect(autocommit=False)
    try:
        if a.find:
            for r in find(conn, a.find, a.city or ""):
                print(r)
            return
        if a.id:
            if a.status:
                res = freshness.set_status(conn, "listing", a.id, a.status, reason=a.reason or "log_deal.py")
                print("status:", res)
            if a.drive_folder:
                conn.execute("UPDATE listings SET drive_folder_id=%s WHERE id=%s", (a.drive_folder, a.id))
                print("drive_folder_id set")
            if a.boe_url:
                conn.execute("UPDATE listings SET boe_url=%s WHERE id=%s", (a.boe_url, a.id))
                print("boe_url set")
            conn.commit(); return
        if a.address:
            hits = find(conn, a.address, a.city)
            if hits:
                print("EXISTS, not inserted:"); [print(" ", h) for h in hits]; return
            ask_c = int(a.price * 100) if a.price else None
            status, reasons = routing.route(a.state, a.city, a.units, a.price)
            lid = conn.execute(
                """INSERT INTO listings (address, city, state, units, asking_price, price_per_unit,
                     year_built, status, source, broker_name, broker_email, notes, drive_folder_id,
                     boe_url, date_ingested, last_seen_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW()) RETURNING id""",
                (a.address, a.city, a.state.upper(), a.units, ask_c,
                 (ask_c // a.units) if (ask_c and a.units) else None, a.year_built, status,
                 a.source, a.broker, a.broker_email, a.notes, a.drive_folder, a.boe_url)).fetchone()[0]
            conn.execute(
                "INSERT INTO listing_history (listing_id, field, old_value, new_value, changed_at, source) "
                "VALUES (%s,'status',NULL,%s,NOW(),'log_deal.py')", (lid, status))
            conn.commit()
            print(f"inserted #{lid} -> {status} ({reasons[0]})")
            return
        ap.print_help()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
