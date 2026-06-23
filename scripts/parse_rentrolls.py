"""Phase 3 step 1 runner — scan Deal Flow for rent-roll attachments, map each to its
listing (by thread id), parse, and write rent_comps. Dry-run by default (--commit)."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect
from ingest import gmail_client as gc, attachments, rentroll

COMMIT = "--commit" in sys.argv


def main():
    svc = gc.service()
    with connect(autocommit=False) as conn:
        total = 0
        for mid in gc.list_message_ids(svc, "Deal Flow"):
            m = gc.get_message(svc, mid)
            for a in m["attachments"]:
                if attachments.classify(a["filename"], a["mime"]) != "rent_roll":
                    continue
                listing = conn.execute(
                    "SELECT id, address, city FROM listings WHERE raw_email_id=%s "
                    "ORDER BY id LIMIT 1", (m["thread_id"],)).fetchone()
                if not listing:
                    print(f"  {a['filename']}: no listing for thread {m['thread_id']} — skip")
                    continue
                lid, addr, city = listing
                data = gc.download_attachment(svc, m["id"], a["attachment_id"])
                units = rentroll.parse_pdf(data)
                occ = [u for u in units if u.get("occupied", True) and u.get("rent")]
                print(f"\n{a['filename']} -> listing #{lid} ({addr}, {city})")
                print(f"  parsed {len(units)} units, {len(occ)} occupied with rent:")
                for u in occ:
                    print(f"    {u.get('unit_type'):<6} {str(u.get('sqft') or '?'):>5}sf  "
                          f"${u.get('rent'):>5}/mo  (beds {u.get('beds')})")
                n = rentroll.write_rent_comps(conn, lid, addr, city, units)
                total += n
                print(f"  wrote {n} rent_comps rows")
        if COMMIT:
            conn.commit(); print(f"\nCOMMITTED {total} rent_comps rows.")
        else:
            conn.rollback(); print(f"\n(dry-run) would write {total} rows. Use --commit.")


if __name__ == "__main__":
    main()
