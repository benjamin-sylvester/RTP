"""Brokers -> organizations (brokerage) and people (role 'broker'), then link listings and
packages to them (broker_person_id / broker_org_id).
Sources: (1) the brokers who actually send deals: distinct broker_name / broker_email in
listings and packages; (2) the CoStar-derived Agent Outreach List (120 agents) in
'MA & NH Broker List.xlsx' with phone and deal counts.
  python scripts/import_brokers.py [--sandbox] [--commit]
"""
import os
import re
import sys

import openpyxl
import psycopg
from _conn import connect, load_env

XLSX = r"G:\Shared drives\RTP G-Drive\2.0 Acquisitions\3.0 Market Data & Reports\MA & NH Broker List.xlsx"

# email domain -> brokerage name (known senders); unknown domains become an org named by domain
DOMAIN_ORG = {
    "htapartments.com": "Horvath & Tremblay", "graypropertygroup.com": "Gray Property Group",
    "portercapitalrei.com": "Porter Capital REI / eXp", "exprealty.com": "eXp Realty",
    "candorealty.com": "Cando Realty", "cbrealty.com": "Coldwell Banker Realty",
    "trophycommercial.com": "Trophy Commercial", "fallriverpm.com": "Fall River Property Management",
    "mlspin.com": "MLS PIN (saved search)", "freedommanagement.net": "Freedom Management",
    "bostonrealtyadvisors.com": "Boston Realty Advisors", "kw.com": "Keller Williams",
}
GENERIC = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "aol.com"}


def conn_for(argv):
    if "--sandbox" in argv:
        load_env()
        return psycopg.connect(os.environ["SANDBOX_DATABASE_URL"], autocommit=False)
    return connect(autocommit=False)


def canon(name):
    name = re.sub(r"\s+", " ", (name or "")).strip()
    return {"William Peck": "Will Peck"}.get(name, name)


def main():
    c = conn_for(sys.argv)
    n = {"org": 0, "person": 0, "email": 0, "listings_linked": 0, "packages_linked": 0, "agents": 0}

    def org(name, kind="brokerage", **f):
        r = c.execute("SELECT id FROM organizations WHERE lower(name)=lower(%s) ORDER BY id LIMIT 1", (name,)).fetchone()
        if r:
            return r[0]
        n["org"] += 1
        return c.execute("INSERT INTO organizations (name, kind, city, state, source) VALUES (%s,%s,%s,%s,'brokers') RETURNING id",
                         (name, kind, f.get("city"), f.get("state"))).fetchone()[0]

    def person(name, email=None, oid=None, phone=None, notes=None):
        pid = None
        if email:
            r = c.execute("SELECT person_id FROM people_emails WHERE email=%s", (email,)).fetchone()
            pid = r[0] if r else None
        if pid is None:
            r = c.execute("SELECT id FROM people WHERE lower(full_name)=lower(%s) AND merged_into_id IS NULL ORDER BY id LIMIT 1", (name,)).fetchone()
            pid = r[0] if r else None
        if pid is None:
            parts = name.split()
            pid = c.execute("INSERT INTO people (full_name, first_name, last_name, org_id, roles, phone, notes, source) "
                            "VALUES (%s,%s,%s,%s,ARRAY['broker'],%s,%s,'brokers') RETURNING id",
                            (name, parts[0], parts[-1] if len(parts) > 1 else None, oid, phone, notes)).fetchone()[0]
            n["person"] += 1
        else:
            c.execute("UPDATE people SET roles=(SELECT array_agg(DISTINCT x) FROM unnest(roles || ARRAY['broker']::text[]) x), "
                      "org_id=COALESCE(org_id,%s), phone=COALESCE(phone,%s), notes=COALESCE(notes,%s) WHERE id=%s", (oid, phone, notes, pid))
        if email and not c.execute("SELECT 1 FROM people_emails WHERE email=%s", (email,)).fetchone():
            c.execute("INSERT INTO people_emails (person_id, email, is_primary, label) VALUES (%s,%s,true,'work')", (pid, email))
            n["email"] += 1
        return pid

    # 1. brokers who send deals
    rows = c.execute("SELECT broker_name, lower(broker_email), count(*) FROM listings WHERE broker_name IS NOT NULL OR broker_email IS NOT NULL "
                     "GROUP BY 1,2 UNION SELECT broker_name, lower(broker_email), 0 FROM packages WHERE broker_name IS NOT NULL").fetchall()
    for name, email, cnt in rows:
        name = canon(name)
        if not name and email:
            name = email.split("@")[0].replace(".", " ").title()
        if not name:
            continue
        domain = email.split("@")[1] if email and "@" in email else None
        oid = None
        if domain and domain not in GENERIC:
            oid = org(DOMAIN_ORG.get(domain, domain))
        pid = person(name, email if (email and domain not in GENERIC and not domain.startswith("mlspin")) else email, oid)
        cur = c.execute("UPDATE listings SET broker_person_id=%s, broker_org_id=COALESCE(broker_org_id,%s) WHERE broker_person_id IS NULL AND "
                  "((lower(broker_email)=%s::text AND %s::text IS NOT NULL) OR (broker_email IS NULL AND broker_name=%s) OR (%s::text IS NULL AND broker_name=%s))",
                  (pid, oid, email, email, name, email, name))
        n["listings_linked"] += cur.rowcount
        cur = c.execute("UPDATE packages SET broker_person_id=%s WHERE broker_person_id IS NULL AND broker_name=%s", (pid, name))
        n["packages_linked"] += cur.rowcount

    # 2. CoStar top agents (reference contacts, not yet relationships)
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb["Agent Outreach List"]
    hdr = None
    for row in ws.iter_rows(values_only=True):
        if row and row[0] == "Rank":
            hdr = [str(h).strip() for h in row]; continue
        if not hdr or not row or not row[1]:
            continue
        d = dict(zip(hdr, row))
        oid = org(str(d["Brokerage"]).strip(), city=d.get("City"), state=d.get("State")) if d.get("Brokerage") else None
        phone = re.sub(r"\D", "", str(d.get("Phone") or "")) or None
        notes = (f"CoStar top listing agent (Apr 2026): {d.get('Deal Count')} deals, {d.get('Total Units')} units, "
                 f"${d.get('Total Volume ($)') or 0:,.0f}; markets {d.get('Markets Active')}; cities {d.get('Property Cities')}")
        person(str(d["Agent Name"]).strip(), None, oid, phone, notes)
        n["agents"] += 1

    print("counts:", n)
    print("brokers:", c.execute("SELECT count(*) FROM people WHERE 'broker' = ANY(roles)").fetchone()[0],
          "| brokerages:", c.execute("SELECT count(*) FROM organizations WHERE kind='brokerage'").fetchone()[0],
          "| listings with broker_person:", c.execute("SELECT count(*) FROM listings WHERE broker_person_id IS NOT NULL").fetchone()[0])
    for r in c.execute("SELECT broker, sum(listings_sent), sum(bid_on) FROM v_broker_activity GROUP BY 1 ORDER BY 2 DESC LIMIT 8"):
        print("   ", r)
    if "--commit" in sys.argv:
        c.commit(); print("COMMITTED")
    else:
        c.rollback(); print("DRY-RUN, rolled back")


if __name__ == "__main__":
    main()
