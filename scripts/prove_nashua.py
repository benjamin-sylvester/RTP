"""Proof: ingesting the Candor '6-Unit in Nashua' email must ENRICH seeded lead #25
(add price + unit mix + NOI), create NO duplicate row, and log to listing_history.
Transactional, but ROLLS BACK by default so it's safe to re-run; pass --commit to persist."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect
from ingest import gmail_client as gc, parsers, dedup

COMMIT = "--commit" in sys.argv


def find_email(svc):
    for mid in gc.list_message_ids(svc, "Deal Flow"):
        m = gc.get_message(svc, mid)
        if gc.match_broker(m["from_email"]) == "candor" and "Nashua" in m["subject"]:
            return m
    return None


def snapshot(cur, lid):
    r = cur.execute(
        "SELECT address, city, units, asking_price, price_per_unit, building_sf, status "
        "FROM listings WHERE id=%s", (lid,)).fetchone()
    f = cur.execute(
        "SELECT gross_revenue, noi, confidence FROM listing_financials WHERE listing_id=%s",
        (lid,)).fetchone()
    um = cur.execute("SELECT count(*) FROM unit_mix WHERE listing_id=%s", (lid,)).fetchone()[0]
    return r, f, um


def main():
    svc = gc.service()
    m = find_email(svc)
    if not m:
        sys.exit("Candor Nashua email not found.")
    body = m["plain"].strip() or parsers.html_to_text(m["html"])
    data = parsers.ai_extract(body, source_label="candor")
    listings = data.get("listings", [])
    print(f"Parsed {len(listings)} listing(s) from '{m['subject']}'\n")
    cand = listings[0]
    cand["thread_id"] = m["thread_id"]
    print(f"Candidate: {cand.get('city')} {cand.get('units')}u "
          f"price=${(cand.get('asking_price') or 0):,} GSI=${(cand.get('gross_revenue') or 0):,} "
          f"NOI=${(cand.get('noi') or 0):,} unit_mix={len(cand.get('unit_mix') or [])}\n")

    with connect(autocommit=False) as conn, conn.cursor() as cur:
        before_count = cur.execute("SELECT count(*) FROM listings").fetchone()[0]
        lid_target = cur.execute(
            "SELECT id FROM listings WHERE raw_email_id=%s", ("19e7064253032ca2",)
        ).fetchone()
        lid_target = lid_target[0] if lid_target else None
        print(f"Seeded Nashua lead id (thread 19e706...): {lid_target}")
        b_row, b_fin, b_um = snapshot(cur, lid_target)
        print(f"BEFORE  listings: {b_row}")
        print(f"BEFORE  financials: {b_fin}  unit_mix rows: {b_um}\n")

        result = dedup.upsert(conn, cand, source="broker_email",
                              raw_email_id=m["thread_id"])
        print(f"UPSERT RESULT: {result}\n")

        after_count = cur.execute("SELECT count(*) FROM listings").fetchone()[0]
        a_row, a_fin, a_um = snapshot(cur, result["listing_id"])
        print(f"AFTER   listings: {a_row}")
        print(f"AFTER   financials: {a_fin}  unit_mix rows: {a_um}")
        print(f"\nRow count: {before_count} -> {after_count} "
              f"({'NO new row (correct)' if after_count==before_count else 'DUPLICATE CREATED (BUG)'})")

        print("\nlisting_history for this listing:")
        for f, o, n in cur.execute(
            "SELECT field, old_value, new_value FROM listing_history "
            "WHERE listing_id=%s ORDER BY id", (result["listing_id"],)).fetchall():
            print(f"  {f}: {o!r} -> {n!r}")

        ok = (result["action"] == "enriched" and result["listing_id"] == lid_target
              and after_count == before_count)
        print(f"\nPROOF: {'PASS' if ok else 'FAIL'} "
              f"(enriched #{lid_target}, no duplicate)")
        if COMMIT and ok:
            conn.commit(); print("COMMITTED.")
        else:
            conn.rollback(); print("ROLLED BACK (dry-run; pass --commit to persist).")


if __name__ == "__main__":
    main()
