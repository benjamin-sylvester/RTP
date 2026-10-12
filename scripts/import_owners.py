"""Import the scored NH owner list (455 owners embedded in RTP-CallDashboard/Code.gs, which mirrors
the live 'RTP Call Tracker' Google Sheet) into organizations (owner entities), people (owner
contacts, role 'owner', score and tier), properties (the building each owner holds, with
owner_of_record) and interactions (pre-seeded call outcomes).
Idempotent: properties by address_key, orgs by name, people by (name, phone).
  python scripts/import_owners.py [--sandbox] [--commit]
"""
import datetime as dt
import json
import os
import re
import sys

import psycopg
from _conn import connect, load_env, ROOT

CODE_GS = ROOT.parent / "RTP-CallDashboard" / "Code.gs"
ENTITY_RE = re.compile(r"\b(llc|l\.l\.c|inc\b|inc\.|trust|properties|property|realty|holdings|partners|"
                       r"associates|group|corp|company|co\.|capital|investments|management|lp\b|ltd|"
                       r"apartments|development|enterprises|ventures|estates|homes)", re.I)
OUTCOME = {"sellnow": "Sell now", "later": "Sell later", "maybe": "Maybe / warm", "no": "Not selling",
           "noanswer": "No answer", "wrong": "Wrong number"}


def conn_for(argv):
    if "--sandbox" in argv:
        load_env()
        return psycopg.connect(os.environ["SANDBOX_DATABASE_URL"], autocommit=False)
    return connect(autocommit=False)


def load_owners():
    src = CODE_GS.read_text(encoding="utf8")
    m = re.search(r"var OWNERS\s*=\s*(\[.*?\]);", src, re.S)
    return json.loads(m.group(1))


def money(s):
    s = re.sub(r"[^\d.]", "", s or "")
    return int(round(float(s) * 100)) if s else None


def date(s):
    try:
        return dt.datetime.strptime(s, "%m/%d/%Y").date() if s else None
    except ValueError:
        return None


def main():
    c = conn_for(sys.argv)
    owners = load_owners()
    n = {"org": 0, "person": 0, "property": 0, "interaction": 0, "linked": 0}
    ben = c.execute("SELECT id FROM people WHERE full_name='Ben Sylvester'").fetchone()[0]
    for o in owners:
        own, contact, phone = (o.get("own") or "").strip(), (o.get("c") or "").strip(), re.sub(r"\D", "", o.get("ph") or "")
        loc = (o.get("loc") or "").strip()
        city_st = re.match(r"(.*?),\s*([A-Z]{2})", loc)
        o_city, o_state = (city_st.group(1), city_st.group(2)) if city_st else (None, None)
        src = "call_list"
        oid = pid = None
        if own and ENTITY_RE.search(own):
            r = c.execute("SELECT id FROM organizations WHERE lower(name)=lower(%s) AND kind='owner_entity'", (own,)).fetchone()
            oid = r[0] if r else c.execute(
                "INSERT INTO organizations (name, kind, city, state, source, notes) VALUES (%s,'owner_entity',%s,%s,%s,%s) RETURNING id",
                (own, o_city, o_state, src, f"Owner of record per CoStar. Portfolio size {o.get('pf')}.")).fetchone()[0]
            if not r: n["org"] += 1
        person_name = contact or (own if own and not oid else "")
        if person_name:
            r = c.execute("SELECT id FROM people WHERE lower(full_name)=lower(%s) AND (phone=%s OR phone IS NULL OR %s='') AND merged_into_id IS NULL LIMIT 1",
                          (person_name, phone, phone)).fetchone()
            if r:
                pid = r[0]
                c.execute("UPDATE people SET roles=(SELECT array_agg(DISTINCT x) FROM unnest(roles || ARRAY['owner']::text[]) x), "
                          "owner_score=GREATEST(COALESCE(owner_score,0), %s), owner_tier=COALESCE(owner_tier,%s), phone=COALESCE(phone,NULLIF(%s,'')), "
                          "org_id=COALESCE(org_id,%s) WHERE id=%s", (o.get("sc"), o.get("t"), phone, oid, pid))
            else:
                parts = person_name.split()
                pid = c.execute(
                    "INSERT INTO people (full_name, first_name, last_name, org_id, roles, phone, city, state, owner_score, owner_tier, source, source_id) "
                    "VALUES (%s,%s,%s,%s,ARRAY['owner'],NULLIF(%s,''),%s,%s,%s,%s,%s,%s) RETURNING id",
                    (person_name, parts[0], parts[-1] if len(parts) > 1 else None, oid, phone, o_city, o_state,
                     o.get("sc"), o.get("t"), src, f"{o.get('a')}|{o.get('ci')}")).fetchone()[0]
                n["person"] += 1
        # the building
        addr, city = (o.get("a") or "").strip(), (o.get("ci") or "").strip()
        if addr and city:
            r = c.execute("SELECT id FROM properties WHERE address_key = rtp_normalize_address(%s,%s,'NH')", (addr, city)).fetchone()
            units = int(o["u"]) if str(o.get("u") or "").isdigit() else None
            yb = int(o["yb"]) if str(o.get("yb") or "").isdigit() else None
            cls = o.get("cl") if o.get("cl") in ("A", "B", "C") else None
            note = (f"Owner call list: tier {o.get('t')} score {o.get('sc')}; corridor {o.get('co')}; years owned {o.get('yo')}; "
                    f"last sale {o.get('ls')} {o.get('lp')}; vacancy {o.get('vac') or 'n/a'}; OOS owner {o.get('oos')}")
            if r:
                prop_id = r[0]
                c.execute("UPDATE properties SET owner_of_record=COALESCE(owner_of_record,%s), owner_org_id=COALESCE(owner_org_id,%s), "
                          "units=COALESCE(units,%s), year_built=COALESCE(year_built,%s), property_class=COALESCE(property_class,%s), "
                          "notes=CASE WHEN notes IS NULL THEN %s WHEN position('Owner call list' in notes)>0 THEN notes ELSE notes||E'\\n'||%s END WHERE id=%s",
                          (own or None, oid, units, yb, cls, note, note, prop_id))
                n["linked"] += 1
            else:
                c.execute("INSERT INTO properties (address, city, state, units, year_built, property_class, owner_of_record, owner_org_id, notes) "
                          "VALUES (%s,%s,'NH',%s,%s,%s,%s,%s,%s)", (addr, city, units, yb, cls, own or None, oid, note))
                n["property"] += 1
        # pre-seeded call outcomes
        if o.get("seed") and (pid or oid):
            sid = f"{addr}|{city}"
            if not c.execute("SELECT 1 FROM interactions WHERE source='call_list_seed' AND source_id=%s", (sid,)).fetchone():
                c.execute("INSERT INTO interactions (person_id, org_id, channel, direction, occurred_at, summary, by_person_id, source, source_id) "
                          "VALUES (%s,%s,'call','outbound','2026-08-11 12:00-04',%s,%s,'call_list_seed',%s)",
                          (pid, oid, f"Cold call outcome: {OUTCOME.get(o['seed'], o['seed'])}. {o.get('snote') or ''}".strip(), ben, sid))
                n["interaction"] += 1
    print("counts:", n)
    print("owners total:", c.execute("SELECT count(*) FROM people WHERE 'owner' = ANY(roles)").fetchone()[0],
          "| owner entities:", c.execute("SELECT count(*) FROM organizations WHERE kind='owner_entity'").fetchone()[0],
          "| properties:", c.execute("SELECT count(*), count(*) FILTER (WHERE owner_of_record IS NOT NULL) FROM properties").fetchone())
    print("by tier:", c.execute("SELECT owner_tier, count(*) FROM people WHERE 'owner' = ANY(roles) GROUP BY 1 ORDER BY 1").fetchall())
    if "--commit" in sys.argv:
        c.commit(); print("COMMITTED")
    else:
        c.rollback(); print("DRY-RUN, rolled back")


if __name__ == "__main__":
    main()
