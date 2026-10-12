"""Phase 0 triage (2026-10-12): fix the engagement-module false positives from the 10/6
wholesale ingest, clear the needs_review quarantine, resolve duplicate groups, and set Drive
folder pointers on active deals and owned assets. Every status move goes through
freshness.set_status (logged to listing_history with a reason) so it can be reversed.

Dry-run by default; --commit to persist.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect
from ingest import freshness

R = "10/12 Phase 0 triage"

# (id, new_status, reason)
STATUS = [
    # owned assets that the engagement module mis-promoted
    (483, "owned", f"{R}: 186 John St is an RTP-owned asset (Fall River MA)"),
    (343, "owned", f"{R}: 42-44 Summer St is an RTP-owned asset; was flipped off owned on 10/7"),
    # closing announcement Ben forwarded to Justin, not an LOI
    (516, "comp_only", f"{R}: 575 N Main closing announcement forwarded to Justin; not an RTP LOI"),
    # out-of-market loi_sent rows set by the engagement module on 10/6; RTP LOIs since June
    # were Seacoast 58, 63 Stark, 46 Main, C St, Cushing, South Coast 2-pack, Seacoast 8, Lafayette
    (411, "comp_only", f"{R}: engagement false positive (Worcester); no RTP LOI"),
    (412, "comp_only", f"{R}: engagement false positive (Worcester); no RTP LOI"),
    (413, "comp_only", f"{R}: engagement false positive (Lynn); no RTP LOI"),
    (414, "comp_only", f"{R}: engagement false positive (Boston); no RTP LOI"),
    # stray 'underwriting' row with no city/units; almost certainly 1331 Elm (#345) misspelled
    (487, "passed", f"{R}: no city/units; likely a typo of #345 1331 Elm St; engagement false positive"),
    # out-of-state lead
    (499, "comp_only", f"{R}: Winston-Salem NC, outside buy box"),
    # Lakeside Landing duplicate still at lead (#335 is the real row, passed by Grossman 9/8)
    (348, "passed", f"{R}: duplicate of #335 Lakeside Landing (passed)"),
    # needs_review: NH rows with an address but no unit count, from spring MLS exports, stale
    (293, "comp_only", f"{R}: stale spring MLS stub, units unknown"),
    (305, "comp_only", f"{R}: stale spring MLS stub, units unknown"),
    (309, "comp_only", f"{R}: stale spring MLS stub, units unknown"),
    (310, "comp_only", f"{R}: stale spring MLS stub, units unknown"),
    (311, "comp_only", f"{R}: stale spring MLS stub, units unknown"),
    (312, "comp_only", f"{R}: 16-18 Cushing St Dover; deal died on seller floor (Aug); keep as comp"),
    (297, "comp_only", f"{R}: 223 High St Somersworth 4u, fits box but last seen 8/5 (stale)"),
    (313, "lead", f"{R}: 20-22 Kirkland St Dover 3u, in box under the 2-50 rule, seen 10/6"),
    # needs_review: no usable address, out of market or out of box; drop from every view
    (278, "passed", f"{R}: no address, March 2026, stale"),
    (280, "passed", f"{R}: no address, March 2026, stale"),
    (281, "passed", f"{R}: no address, Gardner MA, stale"),
    (351, "passed", f"{R}: no address, MA 75u, out of box"),
    (352, "passed", f"{R}: no address, MA 40u, out of box"),
    (385, "passed", f"{R}: no address, ME"),
    (386, "passed", f"{R}: no address, Medford MA 1u"),
    (387, "passed", f"{R}: no address, Revere MA 2u"),
    (388, "passed", f"{R}: no address, Roslindale MA 1u"),
    (389, "passed", f"{R}: no address, Lynn MA 1u"),
    (401, "passed", f"{R}: no address, Woonsocket RI"),
    (410, "passed", f"{R}: no address, Norway ME"),
    (424, "passed", f"{R}: no address, Boston 130u"),
    (452, "passed", f"{R}: no address, Methuen MA 1u"),
    (453, "passed", f"{R}: no address, Lowell MA 3u"),
    (464, "passed", f"{R}: Beacon St Brookline 56u, out of box, no street number"),
    (493, "passed", f"{R}: Savannah GA 224u"),
    (508, "passed", f"{R}: no address, Dorchester MA"),
    (511, "passed", f"{R}: Hannon St Boston 16u, out of market, no street number"),
]

# field fixes: (id, sql_set, params, note)
FIXES = [
    (483, "city='Fall River', state='MA', drive_folder_id=%s",
     ("176xVIMEm1Q5nQiMbuhFttjKYnNQ2SMCr",), "186 John St: city/state + AUM folder"),
    (343, "drive_folder_id=%s", ("1ET6SWR1kpslCbjpQUzwiuEbw5B2Pdtip",), "Summer St: AUM folder"),
    (491, "city='Manchester', state='NH', drive_folder_id=%s",
     ("17BDn2eIjyLzqWD5JnwMCVfjnhAcYJyDX",), "64 Merrimack (Baxter): city/state + Baxter folder"),
    (490, "drive_folder_id=%s", ("17BDn2eIjyLzqWD5JnwMCVfjnhAcYJyDX",), "46 Pleasant (Baxter): Baxter folder"),
    (349, "drive_folder_id=%s", ("1su_MXkXqI3S4LScBfpaH1oRz-deIQp5w",), "Lafayette: 6.0 Claude deal folder"),
    # 136 W Pearl St Nashua: sold $3.3M (BRA closing 10/2), ingested by the old parser as an ask
    (350, "asking_price=NULL, price_per_unit=NULL, sale_price=330000000, "
          "sale_price_per_unit=16500000, sale_date='2026-10-02', "
          "notes=COALESCE(notes,'')||' [10/12 triage: $3.3M was the SALE price (BRA closing announcement 10/2), 8 pct cap; moved from asking_price]'",
     (), "136 W Pearl: sale fields"),
]


def main(commit):
    conn = connect(autocommit=False)
    try:
        print("=== status moves ===")
        for lid, new, reason in STATUS:
            res = freshness.set_status(conn, "listing", lid, new, reason=reason)
            if res is None:
                print(f"  #{lid}: NOT FOUND"); continue
            flag = "" if res["old"] != new else "  (no change)"
            print(f"  #{lid} {res['name'][:34]:34} {res['old']:12} -> {new}{flag}")
        print("\n=== field fixes ===")
        for lid, setsql, params, note in FIXES:
            n = conn.execute(f"UPDATE listings SET {setsql} WHERE id=%s", (*params, lid)).rowcount
            print(f"  #{lid} {note}: {n} row")
        # 136 W Pearl sale comp: status + history row for the briefing's CLOSED SALES section
        res = freshness.set_status(conn, "listing", 350, "comp_only", reason=f"{R}: sold, comp")
        print(f"  #350 {res['old']} -> comp_only")
        conn.execute("INSERT INTO listing_history (listing_id, field, old_value, new_value) "
                     "VALUES (350,'sale_price',NULL,'330000000')")
        print("\n=== resulting status counts ===")
        for st, n in conn.execute("SELECT status, count(*) FROM listings GROUP BY 1 ORDER BY 2 DESC"):
            print(f"  {st:13} {n}")
        if commit:
            conn.commit(); print("\nCOMMITTED.")
        else:
            conn.rollback(); print("\nDRY-RUN, rolled back. Re-run with --commit to persist.")
    finally:
        conn.close()


if __name__ == "__main__":
    main(commit="--commit" in sys.argv)
