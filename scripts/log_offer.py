"""Log an offer / LOI / counter, or record the response to one (replaces LOIs living only in
Word files and prose).

  --listing 349 --type loi --date 2026-10-08 --price 650000 --to "Justin Porter"
      [--terms '{"seller_note": "$400K at 5 pct IO"}'] [--doc-drive-id <id>] [--notes "..."]
  --package 7 --type loi --date 2026-10-09 --price 8750000 --to "Nick Gray"
  --id 16 --response declined --response-date 2026-10-11 [--response-notes "..."]
  --list [--listing 349 | --package 7]        show offers
Types: indicative, loi, loi_revised, counter_received, psa_draft, psa_executed.
Responses: pending, accepted, declined, countered, expired, withdrawn.
Logging an LOI also moves the deal to loi_sent (manual, sticky) unless it is already further along.
"""
import argparse
import json

from _conn import connect
from ingest import freshness

RANK = {"comp_only": 0, "needs_review": 0, "lead": 1, "underwriting": 2, "loi_sent": 3, "under_contract": 4}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listing", type=int); ap.add_argument("--package", type=int); ap.add_argument("--id", type=int)
    ap.add_argument("--type"); ap.add_argument("--direction", default="sent"); ap.add_argument("--date")
    ap.add_argument("--price", type=float, help="dollars"); ap.add_argument("--to"); ap.add_argument("--terms")
    ap.add_argument("--doc-drive-id"); ap.add_argument("--notes")
    ap.add_argument("--response"); ap.add_argument("--response-date"); ap.add_argument("--response-notes")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    c = connect(autocommit=False)
    try:
        if a.list:
            where, params = "", ()
            if a.listing: where, params = "WHERE o.listing_id=%s", (a.listing,)
            if a.package: where, params = "WHERE o.package_id=%s", (a.package,)
            for r in c.execute(f"SELECT o.id, COALESCE(l.address, pk.name), o.offer_type, o.direction, o.offer_date, o.price_cents/100, o.response, o.response_date, p.full_name "
                               f"FROM offers o LEFT JOIN listings l ON l.id=o.listing_id LEFT JOIN packages pk ON pk.id=o.package_id LEFT JOIN people p ON p.id=o.sent_to_person_id {where} ORDER BY o.offer_date DESC, o.id DESC", params):
                print(r)
            return
        if a.id:
            if a.response:
                c.execute("UPDATE offers SET response=%s, response_date=COALESCE(%s, response_date, CURRENT_DATE), response_notes=COALESCE(%s, response_notes) WHERE id=%s",
                          (a.response, a.response_date, a.response_notes, a.id))
                print(f"offer #{a.id} -> {a.response}")
            if a.doc_drive_id:
                did = c.execute("INSERT INTO documents (drive_file_id, title, doc_type) VALUES (%s,%s,'loi') ON CONFLICT (drive_file_id) DO UPDATE SET title=EXCLUDED.title RETURNING id",
                                (a.doc_drive_id, f"Offer #{a.id} document")).fetchone()[0]
                c.execute("UPDATE offers SET document_id=%s WHERE id=%s", (did, a.id))
            c.commit(); return
        if not (a.listing or a.package) or not a.type or not a.date:
            ap.print_help(); return
        to_id = None
        if a.to:
            r = c.execute("SELECT id FROM people WHERE lower(full_name)=lower(%s) AND merged_into_id IS NULL ORDER BY id LIMIT 1", (a.to,)).fetchone()
            to_id = r[0] if r else None
            if not to_id:
                print(f"note: '{a.to}' not found in people; recorded in notes only")
        did = None
        if a.doc_drive_id:
            did = c.execute("INSERT INTO documents (drive_file_id, title, doc_type, listing_id, package_id) VALUES (%s,%s,'loi',%s,%s) "
                            "ON CONFLICT (drive_file_id) DO UPDATE SET title=EXCLUDED.title RETURNING id",
                            (a.doc_drive_id, f"{a.type} {a.date}", a.listing, a.package)).fetchone()[0]
        oid = c.execute("INSERT INTO offers (listing_id, package_id, offer_type, direction, offer_date, price_cents, terms, document_id, sent_to_person_id, notes) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                        (a.listing, a.package, a.type, a.direction, a.date, int(a.price * 100) if a.price else None,
                         a.terms if a.terms else None, did, to_id, (f"to {a.to}. " if a.to and not to_id else "") + (a.notes or ""))).fetchone()[0]
        print(f"offer #{oid} logged")
        if a.type in ("loi", "loi_revised", "psa_draft", "psa_executed") and a.direction == "sent":
            kind, tid = ("listing", a.listing) if a.listing else ("package", a.package)
            cur = c.execute(f"SELECT status FROM {kind}s WHERE id=%s", (tid,)).fetchone()[0]
            target = "under_contract" if a.type == "psa_executed" else "loi_sent"
            if RANK.get(cur, 0) < RANK[target]:
                res = freshness.set_status(c, kind, tid, target, reason=f"log_offer.py: {a.type} {a.date}")
                print(f"{kind} #{tid} {res['old']} -> {target}")
        c.commit()
    finally:
        c.close()


if __name__ == "__main__":
    main()
