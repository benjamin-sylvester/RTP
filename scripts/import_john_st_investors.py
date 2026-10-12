"""186 John Street LLC investors of record (OA Exhibit A) -> investments. Authoritative over the
tracker's '186 $ in' column: updates funded_cents, commitment_cents and ownership_pct on existing
rows, inserts the rest. Run AFTER import_tracker.py so LP people rows exist.
  python scripts/import_john_st_investors.py [--sandbox] [--commit]
"""
import os
import sys

import psycopg
import psycopg.types.json
from _conn import connect, load_env

# Exhibit A (186 John Street - Exhibit A.pdf): member, contribution, final sharing ratio.
EXHIBIT_A = [
    ("Vlad Kanterman", 25000, 0.0406), ("Larisa Vaynberg", 50000, 0.0812), ("Paige Swinimer", 15000, 0.0244),
    ("Jennifer Durant", 15000, 0.0244), ("Curt D", 10000, 0.0162), ("Bill", 50000, 0.0812),
    ("Tommy Murray", 10000, 0.0162), ("GE Property Holdings, LLC", 20000, 0.0325), ("Dan Rusu", 50000, 0.0812),
    ("Elias Hastings", 35000, 0.0568), ("Sophie Shea", 25000, 0.0406), ("Jichao Xu", 10000, 0.0162),
    ("Michael Sylvester", 10000, 0.0162), ("Gordon Bahr", 10000, 0.0162), ("Ren Lamotte", 10000, 0.0162),
    ("Clem Titsworth", 10000, 0.0162), ("Kyle Titsworth", 11000, 0.0179), ("Aldie Anderson", 25000, 0.0406),
    ("BHS Holdings LLC", 20000, 0.0325), ("Justin Kanterman", 20000, 0.0325),
    ("Rising Tide Partners LLC", 0, 0.30),
]
# Exhibit A name -> name as the tracker / people table has it
ALIASES = {
    "Curt D": "Curt Dohrn", "Bill": "Bill & Kathleen Donnelly", "Jichao Xu": "Chao Xu",
    "Ren Lamotte": "Ren LaMotte", "Vlad Kanterman": "Vlad & Kathy Kanterman",
    "Michael Sylvester": "Mikey Sylvester", "Tommy Murray": "Thomas Murray",
}
# tracker-only investor rows that Exhibit A explains through an entity
ORG_FOR_PERSON = {"John Allen & Brendon (Oran Capital)": "GE Property Holdings, LLC", "Ben Sylvester": "BHS Holdings LLC"}
ORG_MEMBERS = {"GE Property Holdings, LLC": "lp_entity", "BHS Holdings LLC": "personal", "Rising Tide Partners LLC": "sponsor"}


def conn_for(argv):
    if "--sandbox" in argv:
        load_env()
        return psycopg.connect(os.environ["SANDBOX_DATABASE_URL"], autocommit=False)
    return connect(autocommit=False)


def main():
    c = conn_for(sys.argv)
    ent = c.execute("SELECT id FROM entities WHERE short_name='John St LLC'").fetchone()[0]
    ins = upd = 0
    unmatched = []
    for name, usd, pct in EXHIBIT_A:
        pid = oid = None
        if name in ORG_MEMBERS:
            kind = "sponsor" if name.startswith("Rising Tide") else "lp_entity" if "GE Property" in name else "other"
            r = c.execute("SELECT id FROM organizations WHERE lower(name) IN (lower(%s), lower(%s)) ORDER BY id LIMIT 1",
                          (name, name.replace(" LLC", "").replace(",", ""))).fetchone()
            oid = r[0] if r else c.execute("INSERT INTO organizations (name, kind, source) VALUES (%s,%s,'exhibit_a') RETURNING id",
                                           (name, kind)).fetchone()[0]
        else:
            look = ALIASES.get(name, name)
            r = c.execute("SELECT id FROM people WHERE lower(full_name)=lower(%s) AND merged_into_id IS NULL LIMIT 1", (look,)).fetchone()
            if not r:
                first, last = look.split()[0], look.split()[-1]
                r = c.execute("SELECT id FROM people WHERE full_name ILIKE %s AND merged_into_id IS NULL ORDER BY id LIMIT 1",
                              (f"{first}%{last}",)).fetchone()
            if r:
                pid = r[0]
                c.execute("UPDATE people SET roles=(SELECT array_agg(DISTINCT x) FROM unnest(roles || ARRAY['lp']::text[]) x) WHERE id=%s", (pid,))
            else:
                parts = look.split()
                pid = c.execute("INSERT INTO people (full_name, first_name, last_name, roles, lp_tier, source) "
                                "VALUES (%s,%s,%s,ARRAY['lp'],'A','exhibit_a') RETURNING id",
                                (look, parts[0], parts[-1])).fetchone()[0]
                unmatched.append(look)
        is_gp = name.startswith("Rising Tide")
        row = c.execute("SELECT id FROM investments WHERE entity_id=%s AND person_id IS NOT DISTINCT FROM %s AND investor_org_id IS NOT DISTINCT FROM %s",
                        (ent, pid, oid)).fetchone()
        if row:
            c.execute("UPDATE investments SET commitment_cents=%s, funded_cents=%s, ownership_pct=%s, is_gp=%s, "
                      "notes=COALESCE(notes,'')||' [Exhibit A: $'||%s||', '||%s||' final sharing ratio]', source='exhibit_a' WHERE id=%s",
                      (usd * 100, usd * 100, pct, is_gp, f"{usd:,}", pct, row[0]))
            upd += 1
        else:
            c.execute("INSERT INTO investments (entity_id, person_id, investor_org_id, commitment_cents, funded_cents, funded_on, ownership_pct, is_gp, notes, source) "
                      "VALUES (%s,%s,%s,%s,%s,'2025-11-13',%s,%s,%s,'exhibit_a')",
                      (ent, pid, oid, usd * 100, usd * 100, pct, is_gp, f"Exhibit A: ${usd:,}, {pct:.2%} final sharing ratio"))
            ins += 1
    # tracker-only positions (not on Exhibit A): clear the dollars, keep the row, queue for Ben
    queued = []
    for iid, pname, funded in c.execute(
            "SELECT i.id, p.full_name, i.funded_cents FROM investments i LEFT JOIN people p ON p.id=i.person_id "
            "WHERE i.entity_id=%s AND i.source <> 'exhibit_a'", (ent,)).fetchall():
        via = ORG_FOR_PERSON.get(pname)
        note = (f" [10/12: not a member on Exhibit A; tracker said ${(funded or 0)/100:,.0f}. "
                + (f"Exhibit A member is {via}, likely this person's entity." if via else "CONFIRM.") + "]")
        c.execute("UPDATE investments SET funded_cents=NULL, commitment_cents=NULL, ownership_pct=NULL, notes=COALESCE(notes,'')||%s WHERE id=%s", (note, iid))
        c.execute("INSERT INTO review_queue (kind, ref_table, ref_id, payload) VALUES ('import_conflict','investments',%s,%s) ON CONFLICT DO NOTHING",
                  (iid, psycopg.types.json.Jsonb({"person": pname, "tracker_funded_cents": funded, "exhibit_a_entity": via})))
        queued.append(pname)
    print(f"investments inserted {ins}, updated {upd}; people created (not in tracker): {unmatched}; tracker-only queued: {queued}")
    print("positions:", c.execute("SELECT count(*), sum(funded_cents)/100, sum(ownership_pct) FROM investments WHERE entity_id=%s", (ent,)).fetchone())
    for r in c.execute("SELECT investor, investor_entity, funded_cents/100, ownership_pct FROM v_investor_positions WHERE entity_id=%s ORDER BY funded_cents DESC NULLS LAST", (ent,)):
        print("   ", r)
    if "--commit" in sys.argv:
        c.commit(); print("COMMITTED")
    else:
        c.rollback(); print("DRY-RUN, rolled back")


if __name__ == "__main__":
    main()
