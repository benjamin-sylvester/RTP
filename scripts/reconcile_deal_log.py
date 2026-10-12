"""Reconcile 6.0 Claude/pipeline/deal-log.csv (the Claude Code stopgap log) against listings.

For each CSV row: find a listings match by street number + first street token + city
(case-insensitive). Report MATCH (id, status) or MISSING. With --insert, missing rows are
inserted as listings with source='deal_log_csv' and routed by the buy box; the CSV's notes go
to listings.notes and the BOE link (if any) to boe_url. Dry-run by default.
"""
import csv
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect
from ingest import routing

CSV = pathlib.Path(r"G:\Shared drives\RTP G-Drive\6.0 Claude\pipeline\deal-log.csv")


def key(addr):
    m = re.match(r"\s*(\d+)[^\s]*\s+(\S+)", addr or "")
    return (m.group(1), m.group(2).lower().rstrip(".,")) if m else (None, None)


def main(insert):
    rows = list(csv.DictReader(CSV.open(encoding="utf8")))
    conn = connect(autocommit=False)
    try:
        matched, missing = [], []
        for r in rows:
            num, street = key(r["Address"])
            city = r["City"].strip()
            cands = conn.execute(
                "SELECT id, address, status, units, asking_price FROM listings "
                "WHERE lower(city)=lower(%s) AND address ILIKE %s ORDER BY id",
                (city, f"{num}%{street}%" if num else "%")).fetchall() if num else []
            if cands:
                lid, addr, status, units, ask = cands[0]
                matched.append((r, cands[0]))
                print(f"  MATCH   {r['Address']}, {city}  ->  #{lid} {addr} [{status}] "
                      f"{units}u ${(ask or 0)/100:,.0f}" + (f"  (+{len(cands)-1} more)" if len(cands) > 1 else ""))
            else:
                missing.append(r)
                print(f"  MISSING {r['Address']}, {city}, {r['State']} {r['Units']}u ${r['Asking Price']}  "
                      f"[{r['Source']}]")
        print(f"\n{len(matched)} matched, {len(missing)} missing of {len(rows)} CSV rows")

        if insert and missing:
            print("\n=== inserting missing rows ===")
            for r in missing:
                units = int(r["Units"]) if r["Units"].strip() else None
                ask = int(float(r["Asking Price"])) if r["Asking Price"].strip() else None
                status, reasons = routing.route(r["State"], r["City"], units, ask)
                notes = f"[deal-log.csv {r['Date Added']}] score {r['Score'] or '-'}; buy box: {r['Buy Box']}. {r['Notes']}"
                conn.execute(
                    """INSERT INTO listings (address, city, state, units, asking_price,
                         price_per_unit, year_built, status, source, broker_name, broker_email,
                         notes, boe_url, date_ingested, last_seen_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'deal_log_csv',%s,%s,%s,%s,%s::date,NOW())""",
                    (r["Address"], r["City"], r["State"], units,
                     ask * 100 if ask else None,
                     (ask * 100 // units) if (ask and units) else None,
                     int(r["Year Built"]) if r["Year Built"].strip() else None,
                     status, r["Broker"] or None, r["Broker Email"] or None, notes,
                     r["BOE Link"] or None, r["Date Added"]))
                print(f"  inserted {r['Address']}, {r['City']} -> {status} ({reasons[0]})")
            conn.commit()
            print("COMMITTED.")
        else:
            conn.rollback()
            print("DRY-RUN (no inserts). Re-run with --insert to add the missing rows.")
    finally:
        conn.close()


if __name__ == "__main__":
    main(insert="--insert" in sys.argv)
