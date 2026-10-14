"""People fixes after the tracker import (Ben's dashboard review 10/13/26):
  - rows the tracker wrote as "Firm (Person)" were imported backwards; swap person and firm
  - capital partners inherited the tracker's Priority as an LP tier; clear it (warmth stays)
  - 'John Allen & Brendon (Oran Capital)' -> person John Allen at Oran Capital
  - 'Lora' (Tier A, no email) -> tier cleared, queued for Ben
Dry-run by default; --commit to persist.
"""
import os
import sys

import psycopg
from _conn import connect, load_env


def conn_for(argv):
    if "--sandbox" in argv:
        load_env()
        return psycopg.connect(os.environ["SANDBOX_DATABASE_URL"], autocommit=False)
    return connect(autocommit=False)


def org_id(c, name, kind):
    r = c.execute("SELECT id FROM organizations WHERE lower(name)=lower(%s) LIMIT 1", (name,)).fetchone()
    return r[0] if r else c.execute("INSERT INTO organizations (name, kind, source) VALUES (%s,%s,'fix 10/13') RETURNING id", (name, kind)).fetchone()[0]


def main():
    c = conn_for(sys.argv)
    # 1. swaps: person row id -> (person name, firm name)
    for pid, person, firm in [(7, "Bakari Adams", "Crestway Partners"), (20, "Greg Donahue", "21 George Investors"),
                              (23, "Mark Phillips", "New Era Capital")]:
        old_org = c.execute("SELECT org_id FROM people WHERE id=%s", (pid,)).fetchone()[0]
        oid = org_id(c, firm, "capital_partner")
        parts = person.split()
        c.execute("UPDATE people SET full_name=%s, first_name=%s, last_name=%s, org_id=%s WHERE id=%s", (person, parts[0], parts[-1], oid, pid))
        # the org that carried the person's name is wrong; retire it if nothing else points at it
        if old_org and old_org != oid:
            used = c.execute("SELECT count(*) FROM people WHERE org_id=%s AND id<>%s", (old_org, pid)).fetchone()[0]
            if not used:
                c.execute("UPDATE organizations SET merged_into_id=%s, notes=COALESCE(notes,'')||' [10/13: was a person name imported as a firm]' WHERE id=%s", (oid, old_org))
        print(f"  #{pid} -> {person} @ {firm}")
    # 2. Arcana / VMD mangled row (#25) -> Stephanie Cummings (Arcana Partners) + James Beaton (VMD Companies)
    arc = org_id(c, "Arcana Partners", "capital_partner"); vmd = org_id(c, "VMD Companies", "capital_partner")
    c.execute("UPDATE people SET full_name='Stephanie Cummings', first_name='Stephanie', last_name='Cummings', org_id=%s WHERE id=25", (arc,))
    if not c.execute("SELECT 1 FROM people WHERE lower(full_name)='james beaton'").fetchone():
        c.execute("INSERT INTO people (full_name, first_name, last_name, org_id, roles, warmth, notes, source) VALUES "
                  "('James Beaton','James','Beaton',%s,ARRAY['capital_partner'],'cold','PERE Incubator with Stephanie Cummings (Arcana); met 8/24, follow-up 8/27, no reply','fix 10/13')", (vmd,))
    print("  #25 -> Stephanie Cummings @ Arcana Partners; James Beaton @ VMD Companies added")
    # 3. John Allen & Brendon (Oran Capital)
    oran = org_id(c, "Oran Capital", "lp_entity")
    c.execute("UPDATE people SET full_name='John Allen', first_name='John', last_name='Allen', org_id=%s, "
              "notes=COALESCE(notes,'')||' [10/13: tracker row was John Allen & Brendon (Oran Capital); GE Property Holdings LLC on Exhibit A is likely their vehicle]' WHERE id=37", (oran,))
    ge = c.execute("SELECT id FROM organizations WHERE name ILIKE 'GE Property Holdings%' LIMIT 1").fetchone()
    if ge:
        c.execute("UPDATE organizations SET notes=COALESCE(notes,'')||' [10/13: likely John Allen / Oran Capital vehicle, CONFIRM]' WHERE id=%s", (ge[0],))
    print("  #37 -> John Allen @ Oran Capital")
    # 4. capital partners: Priority is not an LP tier
    n = c.execute("UPDATE people SET notes=COALESCE(notes,'')||' [priority '||lp_tier||' on the capital partners tab]', lp_tier=NULL "
                  "WHERE 'capital_partner'=ANY(roles) AND lp_tier IS NOT NULL AND NOT (roles && ARRAY['lp','lp_prospect']::text[])").rowcount
    print(f"  cleared lp_tier on {n} capital partners (kept in notes)")
    # 5. Lora
    c.execute("UPDATE people SET lp_tier=NULL, notes=COALESCE(notes,'')||' [10/13: no surname or email; not on Exhibit A; CONFIRM who this is]' WHERE full_name='Lora'")
    print("  Lora: tier cleared")
    print("investors tab now:", c.execute("SELECT count(*) FROM v_lp_pipeline").fetchone()[0], "people;",
          c.execute("SELECT count(*) FROM v_lp_pipeline WHERE lp_tier='A'").fetchone()[0], "tier A")
    if "--commit" in sys.argv:
        c.commit(); print("COMMITTED")
    else:
        c.rollback(); print("DRY-RUN, rolled back")


if __name__ == "__main__":
    main()
