"""Backfill the LOI history that the database missed (2026-10-12).

  1. Seacoast 8 (Tim Baxter) as a package: 8 member parcels (6 inserted), status loi_sent
     (LOI v03 $8.75M sent 10/9, declined 10/11, dialogue open).
  2. Seacoast 58 (Will Peck) as a package, status lost (JV LOI ~6/18, dead by ~7/14).
  3. 46 Main St Somersworth (LOI 8/4 $1.25M, no reply) and 3-5 C St Nashua (LOI 8/28, v02 $650K,
     seller went dark 9/8) inserted as lost.
  4. Status fixes: 63 Stark -> lost, 16-18 Cushing -> lost, 9-11 Worster -> passed,
     64 Merrimack -> passed, 46 Pleasant -> comp_only (it is a Seacoast 8 member now).
  5. Lafayette note: LOI terms.
Dry-run by default; --commit to persist. Idempotent: existing rows are found, not re-inserted.
"""
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _conn import connect
from ingest import freshness

R = "10/12 LOI backfill"
BAXTER = "17BDn2eIjyLzqWD5JnwMCVfjnhAcYJyDX"
NICK = ("Nick Gray", "ngray@graypropertygroup.com")
PECK = ("Will Peck", None)
PORTER = ("Justin Porter", "justin@portercapitalrei.com")


def find_or_insert(conn, addr, city, state, units, ask_usd, broker, notes, status="comp_only",
                   year_built=None, drive=None, log=print):
    m = re.match(r"\s*(\d+)[^\s]*\s+(\S+)", addr)
    pattern = f"{m.group(1)}%{m.group(2)}%" if m else addr
    row = conn.execute(
        "SELECT id, status FROM listings WHERE lower(city)=lower(%s) AND address ILIKE %s ORDER BY id LIMIT 1",
        (city, pattern)).fetchone()
    if row:
        log(f"  exists  #{row[0]} {addr}, {city} [{row[1]}]")
        return row[0]
    ask = int(ask_usd * 100) if ask_usd else None
    ppu = (ask // units) if (ask and units) else None
    lid = conn.execute(
        "INSERT INTO listings (address, city, state, units, asking_price, price_per_unit, year_built, "
        "status, source, broker_name, broker_email, notes, drive_folder_id, date_ingested, last_seen_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'manual',%s,%s,%s,%s,NOW(),NOW()) RETURNING id",
        (addr, city, state, units, ask, ppu, year_built, status, broker[0], broker[1],
         f"[{R}] {notes}", drive)).fetchone()[0]
    conn.execute("INSERT INTO listing_history (listing_id, field, old_value, new_value) "
                 "VALUES (%s,'status',NULL,%s)", (lid, status))
    log(f"  insert  #{lid} {addr}, {city} ({units}u) -> {status}")
    return lid


def package(conn, name, market, state, status, units, ask_usd, broker, drive, notes, member_ids, log=print):
    row = conn.execute("SELECT id, status FROM packages WHERE name=%s", (name,)).fetchone()
    if row:
        pid = row[0]
        log(f"  package exists #{pid} {name} [{row[1]}]")
    else:
        pid = conn.execute(
            "INSERT INTO packages (name, market, state, status, total_units, asking_price, broker_name, "
            "broker_email, drive_folder_id, notes, last_seen_at) "
            "VALUES (%s,%s,%s,'comp_only',%s,%s,%s,%s,%s,%s,NOW()) RETURNING id",
            (name, market, state, units, int(ask_usd * 100) if ask_usd else None, broker[0], broker[1],
             drive, f"[{R}] {notes}")).fetchone()[0]
        log(f"  package insert #{pid} {name}")
    n = conn.execute("UPDATE listings SET package_id=%s WHERE id = ANY(%s) AND package_id IS DISTINCT FROM %s",
                     (pid, member_ids, pid)).rowcount
    log(f"  linked {n} member(s)")
    res = freshness.set_status(conn, "package", pid, status, reason=R)
    log(f"  package #{pid} {res['old']} -> {res['new']}")
    return pid


S8 = [
    ("2-6 N Main Street", "Rochester", 27, 3600000, "6NM: 24 res + 3 comm; listed by Will Peck; Rochester Holdings"),
    ("124-126 N Main Street", "Rochester", 8, None, "Rochester Holdings group"),
    ("15-27 Mechanic Street", "Farmington", 12, None, "Rochester Holdings group; 5 buildings incl. a manufactured home"),
    ("67-69 Green Street", "Rochester", 8, None, "Rochester Holdings group; tenant-paid gas and electric"),
    ("22 Fayette Street", "Somersworth", 4, None, "WestEast; Somersworth loan shared with 46 Pleasant; oil boiler"),
    ("46 Pleasant Street", "Somersworth", 2, None, "WestEast; poor exterior, unit 2 stalled rehab"),
    ("65 Green Street", "Rochester", 6, None, "Sixty Five Green LLC; good shape; Tim paid $760K 3/2024"),
    ("19 Winter Street", "Rochester", 3, None, "64 Merrimack LLC; debt $480K"),
]
S8_NOTES = (
    "LOI v03 $8,750,000 all-or-nothing sent to Nick Gray 10/9/26 (deposits $50K + $150K, 45-day DD, "
    "120-day exclusivity, acceptance 10/16). Declined 10/11: Rochester Holdings investors want ~$7.5M for "
    "their four (6NM, 124 Main, Mechanic, 67 Green); Tim sees no need to sell the other four at our ~$2.0M. "
    "Implied floor ~$9.5M. Dialogue open; Ben to reply and decide. Model Seacoast 8 Pack_v12; see pipeline/CLAUDE.md.")

S58 = [
    ("23 Elm Street", "Milton", 12, "Rural; marketed 3BRs are really 2BR"),
    ("6th Street", "Dover", 8, "4 buildings, 8 units"),
    ("260 Main Street", "Somersworth", None, "2006 build, all 2BR/1BA, separate utilities (part of 38 Somersworth units)"),
    ("17-31 Market Street", "Somersworth", None, "3 buildings, new roofs 2025-26, owner-paid heat (part of 38 Somersworth units)"),
    ("62 Green Street", "Somersworth", None, "Next to The Overlook, 135 new units (part of 38 Somersworth units)"),
]
S58_NOTES = (
    "Ask $9.8M with assumable Fannie loan ($6.64M at 3.28 pct). LOI ~6/18/26 as JV with Jason Weissman (TBC), "
    "$9.0M likely to $9.2M (6/23); UW v49 17 pct LP IRR / 2.06x. No result; Will said 7/14 the 38-unit was still "
    "available. Dead by ~7/14. Site visit 6/4: pipeline/deals/seacoast-58-unit.")

FIXES = [
    (506, "lost", f"{R}: LOIs 7/20 $2.25M and 7/22 $2.4-2.45M to Will Peck; lost on price; closing announced 9/28"),
    (312, "lost", f"{R}: offers 8/12 $1.1M and 8/25 $1.15M seller-financed; seller floor $1,272,500; dead 9/1"),
    (489, "passed", f"{R}: walked 9/17, severe tenant damage, dropped from the Baxter scope"),
    (491, "passed", f"{R}: indicative $4.47M 9/29 vs Tim's $6.4M; revisit only at 90 pct occupancy"),
]


def main(commit):
    conn = connect(autocommit=False)
    try:
        print("=== 1. Seacoast 8 (Tim Baxter) ===")
        ids = [find_or_insert(conn, a, c, "NH", u, ask, NICK, n, drive=BAXTER) for a, c, u, ask, n in S8]
        package(conn, "Seacoast 8 (Tim Baxter portfolio)", "Rochester / Somersworth / Farmington", "NH",
                "loi_sent", 70, None, NICK, BAXTER, S8_NOTES, ids)
        res = freshness.set_status(conn, "listing", ids[5], "comp_only",
                                   reason=f"{R}: Seacoast 8 member, the package carries the deal")
        print(f"  #{ids[5]} 46 Pleasant {res['old']} -> comp_only")

        print("\n=== 2. Seacoast 58 (Will Peck) ===")
        ids58 = [find_or_insert(conn, a, c, "NH", u, None, PECK, n) for a, c, u, n in S58]
        package(conn, "Seacoast 58 (Somersworth / Milton / Dover)", "Somersworth / Milton / Dover", "NH",
                "lost", 58, 9800000, PECK, None, S58_NOTES, ids58)

        print("\n=== 3. Other LOIs missing from the DB ===")
        find_or_insert(conn, "46 Main Street", "Somersworth", "NH", 9, 1425000, PECK,
                       "H&T listing at $1.425M (7.80 pct broker cap). Visited 7/30. LOI 8/4 $1,250,000 "
                       "($25K+$25K, 21-day DD, 75-day close). Chased 8/6, no reply. Dead. Drive: 1.0 Dead Deals; "
                       "notes pipeline/deals/46-main-st-somersworth", status="lost", year_built=1950)
        find_or_insert(conn, "3-5 C Street", "Nashua", "NH", None, None, PORTER,
                       "Off-market via Porter. LOI v01 8/28, v02 $650,000; seller went dark 9/8. Bridge quotes shelved.",
                       status="lost")

        print("\n=== 4. Status fixes ===")
        for lid, st, why in FIXES:
            res = freshness.set_status(conn, "listing", lid, st, reason=why)
            print(f"  #{lid} {res['name'][:28]:28} {res['old']:12} -> {st}")

        print("\n=== 5. Lafayette note ===")
        conn.execute("UPDATE listings SET notes=COALESCE(notes,'')||%s WHERE id=349",
                     (f" [{R}: LOI v01 sent to Porter 10/8 at $650,000 with a $400K seller note, 5 pct interest-only "
                      "3 yrs; RTP pays Porter 1.5 pct; acceptance date 10/12; seller silent as of 10/12]",))
        print("  #349 noted")

        print("\n=== after ===")
        for r in conn.execute("SELECT status, count(*) FROM packages GROUP BY 1 ORDER BY 1"):
            print("  packages", r)
        for r in conn.execute("SELECT status, count(*) FROM listings GROUP BY 1 ORDER BY 2 DESC"):
            print("  listings", r)
        if commit:
            conn.commit()
            print("\nCOMMITTED.")
        else:
            conn.rollback()
            print("\nDRY-RUN, rolled back.")
    finally:
        conn.close()


if __name__ == "__main__":
    main(commit="--commit" in sys.argv)
