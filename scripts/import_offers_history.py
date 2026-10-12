"""Seed the offers table with RTP's bid history since June 2026 (from pipeline/CLAUDE.md and the
deal folders). Idempotent: keyed on (listing/package, offer_type, offer_date, price).
  python scripts/import_offers_history.py [--sandbox] [--commit]
"""
import json
import os
import sys

import psycopg
from _conn import connect, load_env


def conn_for(argv):
    if "--sandbox" in argv:
        load_env()
        return psycopg.connect(os.environ["SANDBOX_DATABASE_URL"], autocommit=False)
    return connect(autocommit=False)


def listing_id(c, addr_like, city):
    r = c.execute("SELECT id FROM listings WHERE address ILIKE %s AND lower(city)=lower(%s) ORDER BY id LIMIT 1",
                  (addr_like, city)).fetchone()
    if not r:
        raise SystemExit(f"listing not found: {addr_like}, {city}")
    return r[0]


def package_id(c, name_like):
    r = c.execute("SELECT id FROM packages WHERE name ILIKE %s ORDER BY id LIMIT 1", (name_like,)).fetchone()
    if not r:
        raise SystemExit(f"package not found: {name_like}")
    return r[0]


def person_id(c, name):
    r = c.execute("SELECT id FROM people WHERE lower(full_name)=lower(%s)", (name,)).fetchone()
    return r[0] if r else None


def main():
    c = conn_for(sys.argv)
    P = lambda n: ("package", package_id(c, n))
    L = lambda a, city: ("listing", listing_id(c, a, city))
    usd = lambda x: int(x * 100) if x is not None else None

    rows = [
        # (target, offer_type, direction, date, price_usd, response, response_date, terms, notes, sent_to)
        (P("Seacoast 58%"), "loi", "sent", "2026-06-18", 9000000, "expired", "2026-07-14",
         {"structure": "JV with Jason Weissman / TBC", "assumable_loan": "Fannie $6.64M at 3.28 pct"},
         "JV LOI; bid likely moving to $9.2M on 6/23; no result, dead by ~7/14", "Will Peck"),
        (L("63 Stark%", "Manchester"), "loi", "sent", "2026-07-20", 2250000, "countered", "2026-07-22",
         {"deposit_cents": 10000000, "dd_days": 14, "financing_contingency": "30 days past DD", "exclusivity_days": 75, "acceptance_date": "2026-07-24"},
         "First LOI to Will Peck", "Will Peck"),
        (L("63 Stark%", "Manchester"), "loi_revised", "sent", "2026-07-22", 2400000, "declined", "2026-07-27",
         {"financing_contingency": "written commitment >= 70 pct of price", "acceptance_date": "2026-07-27"},
         "Final LOI file is $2.4M; LP email said best and final $2.45M [CONFIRM]. Lost on price; closing announced 9/28", "Will Peck"),
        (P("282 Sprague%"), "loi", "sent", "2026-07-15", 1450000, "countered", "2026-07-18",
         {}, "Ask $1,625K; seller countered $1,575K", "Lyndsey Pachon"),
        (P("282 Sprague%"), "loi_revised", "sent", "2026-07-24", 1525000, "withdrawn", "2026-07-31",
         {"deposit_cents": 7500000, "deposit_2_cents": 7500000, "dd_days": 14, "financing_days": 30, "allocation": "Sprague $810K / Nelson $715K"},
         "LOI v03 fully executed 7/24; RTP walked 7/31 before the P&S (returns ~1.7-1.8x vs 2.0x bar)", "Lyndsey Pachon"),
        (L("46 Main%", "Somersworth"), "loi", "sent", "2026-08-04", 1250000, "expired", "2026-08-10",
         {"deposit_cents": 2500000, "deposit_2_cents": 2500000, "dd_days": 21, "close_days": 75, "financing_contingency": ">= 70 pct, 30 days past DD", "exclusivity_days": 75, "acceptance_date": "2026-08-10"},
         "Ask $1.425M. Chased 8/6, no reply", "Will Peck"),
        (L("16-18 Cushing%", "Dover"), "loi", "sent", "2026-08-12", 1100000, "countered", None,
         {"seller_note": "$935K at 5 pct IO, 5-yr balloon, 85 pct", "down_cents": 16500000, "deposit_cents": 2000000, "dd_days": 21},
         "Ask $1.299M. Seller-financed structure", "Christy Hoffman"),
        (L("16-18 Cushing%", "Dover"), "loi_revised", "sent", "2026-08-25", 1150000, "declined", "2026-09-01",
         {"seller_note": "85 pct seller financing"}, "Seller floor $1,272,500; dead 9/1", "Christy Hoffman"),
        (L("3-5 C St%", "Nashua"), "loi", "sent", "2026-08-28", None, "expired", "2026-09-08",
         {}, "LOI v01; price not recorded in notes [CONFIRM]", "Justin Porter"),
        (L("3-5 C St%", "Nashua"), "loi_revised", "sent", "2026-09-01", 650000, "expired", "2026-09-08",
         {}, "LOI v02 $650K; seller went dark 9/8 (v02 date approximate)", "Justin Porter"),
        (L("64 Merrimack%", "Manchester"), "indicative", "sent", "2026-09-29", 4470000, "declined", "2026-09-30",
         {"basis": "current occupancy 27 of 45"}, "Tim needs $6.4M before costs", "Nick Gray"),
        (P("Seacoast 8%"), "indicative", "sent", "2026-09-29", 8640000, "countered", "2026-09-30",
         {"note": "per-asset indicative bids, Seacoast primary $9.39M incl. assets later dropped; the 8 at $8.64M"},
         "Tim via Nick 9/30: RH needs $7.5M to $8M; deal possible on Fayette, Pleasant, 65 Green, 19 Winter, 396 Cedar", "Nick Gray"),
        (P("Seacoast 8%"), "loi", "sent", "2026-10-09", 8750000, "declined", "2026-10-11",
         {"deposit_cents": 5000000, "deposit_2_cents": 15000000, "dd_days": 45, "close_days": 30, "exclusivity_days": 120,
          "acceptance_date": "2026-10-16", "all_or_nothing": True, "allocation": "Seller's election in PSA, total fixed"},
         "LOI v03. Declined 10/11: RH investors want ~$7.5M; dialogue open", "Nick Gray"),
        (L("16-20 Lafayette%", "Rochester"), "indicative", "sent", "2026-10-06", 625000, "countered", "2026-10-06",
         {}, "11:45am ET; Porter asked about seller financing", "Justin Porter"),
        (L("16-20 Lafayette%", "Rochester"), "indicative", "sent", "2026-10-06", 650000, "countered", "2026-10-06",
         {"seller_note": "$400K at 5 pct IO, 3 yrs"}, "6:18pm ET; Porter asked for an LOI including his fee", "Justin Porter"),
        (L("16-20 Lafayette%", "Rochester"), "loi", "sent", "2026-10-08", 650000, "pending", None,
         {"seller_note": "$400K at 5 pct IO, 3 yrs", "broker_fee": "RTP pays Porter 1.5 pct", "acceptance_date": "2026-10-12"},
         "LOI v01 sent 2:35pm ET; seller silent as of 10/12", "Justin Porter"),
    ]
    ins = skip = 0
    for (kind, tid), otype, direction, date, price, resp, rdate, terms, notes, to in rows:
        col = "listing_id" if kind == "listing" else "package_id"
        exists = c.execute(f"SELECT id FROM offers WHERE {col}=%s AND offer_type=%s AND offer_date=%s AND price_cents IS NOT DISTINCT FROM %s",
                           (tid, otype, date, usd(price))).fetchone()
        if exists:
            skip += 1; continue
        c.execute(f"INSERT INTO offers ({col}, offer_type, direction, offer_date, price_cents, terms, sent_to_person_id, "
                  "response, response_date, notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                  (tid, otype, direction, date, usd(price), json.dumps(terms), person_id(c, to), resp, rdate,
                   f"[offers history 10/12] to {to}. {notes}"))
        ins += 1
        print(f"  + {kind} #{tid} {otype} {date} {('$%s' % format(price, ',')) if price else '-'} -> {resp}")
    print(f"inserted {ins}, skipped {skip}")
    if "--commit" in sys.argv:
        c.commit(); print("COMMITTED")
    else:
        c.rollback(); print("DRY-RUN, rolled back")


if __name__ == "__main__":
    main()
