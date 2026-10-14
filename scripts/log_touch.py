"""Log a relationship touch or an action item from the command line (used by the daily email
review and by Claude sessions; replaces editing the tracker xlsx).

  --who "Russell Brott" [--email russell@thebrottco.com] [--org "The Brott Company"] [--role lp_prospect]
      [--touch "Yes to the LP list" --channel linkedin --direction inbound --when 2026-10-12 --source "linkedin" --source-id "<id>"]
      [--action "Send the overview deck" --due 2026-10-16 --category capital --details "..."]
      [--done "<action title substring>"]        mark an open action done
      [--note "..."]                             append to the person's notes
      [--tier B] [--deal 349]                    LP tier; link the touch to a listing id
  --find "brott"                                 search people

Creates the person (and org) if missing. Idempotent on (source, source_id) for touches.
"""
import argparse
import datetime as dt
import sys

from _conn import connect


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--find"); ap.add_argument("--who"); ap.add_argument("--email"); ap.add_argument("--org")
    ap.add_argument("--role"); ap.add_argument("--tier"); ap.add_argument("--note")
    ap.add_argument("--touch"); ap.add_argument("--channel", default="email")
    ap.add_argument("--direction", default="mutual"); ap.add_argument("--when")
    ap.add_argument("--source"); ap.add_argument("--source-id"); ap.add_argument("--deal", type=int)
    ap.add_argument("--action"); ap.add_argument("--due"); ap.add_argument("--done")
    ap.add_argument("--category", choices=["deal", "capital", "property", "admin", "network"]); ap.add_argument("--details")
    a = ap.parse_args()
    c = connect(autocommit=False)
    ben = c.execute("SELECT id FROM people WHERE full_name='Ben Sylvester'").fetchone()[0]
    try:
        if a.find:
            for r in c.execute("SELECT p.id, p.full_name, p.roles, p.lp_tier, (SELECT string_agg(email,'; ') FROM people_emails e WHERE e.person_id=p.id), "
                               "(SELECT max(occurred_at)::date FROM interactions i WHERE i.person_id=p.id) FROM people p "
                               "WHERE p.full_name ILIKE %s OR EXISTS (SELECT 1 FROM people_emails e WHERE e.person_id=p.id AND e.email ILIKE %s) ORDER BY p.id",
                               (f"%{a.find}%", f"%{a.find}%")):
                print(r)
            return
        if not a.who:
            ap.print_help(); return
        pid = None
        if a.email:
            r = c.execute("SELECT person_id FROM people_emails WHERE email=%s", (a.email.lower(),)).fetchone()
            pid = r[0] if r else None
        if pid is None:
            r = c.execute("SELECT id FROM people WHERE lower(full_name)=lower(%s) AND merged_into_id IS NULL ORDER BY id LIMIT 1", (a.who,)).fetchone()
            pid = r[0] if r else None
        oid = None
        if a.org:
            r = c.execute("SELECT id FROM organizations WHERE lower(name)=lower(%s) ORDER BY id LIMIT 1", (a.org,)).fetchone()
            oid = r[0] if r else c.execute("INSERT INTO organizations (name, kind, source) VALUES (%s,'other','log_touch') RETURNING id", (a.org,)).fetchone()[0]
        if pid is None:
            parts = a.who.split()
            pid = c.execute("INSERT INTO people (full_name, first_name, last_name, org_id, roles, lp_tier, source) VALUES (%s,%s,%s,%s,%s,%s,'log_touch') RETURNING id",
                            (a.who, parts[0], parts[-1] if len(parts) > 1 else None, oid, [a.role] if a.role else [], a.tier)).fetchone()[0]
            print(f"created person #{pid} {a.who}")
        else:
            if a.role:
                c.execute("UPDATE people SET roles=(SELECT array_agg(DISTINCT x) FROM unnest(roles || %s::text[]) x) WHERE id=%s", ([a.role], pid))
            if a.tier:
                c.execute("UPDATE people SET lp_tier=%s WHERE id=%s", (a.tier, pid))
            if oid:
                c.execute("UPDATE people SET org_id=COALESCE(org_id,%s) WHERE id=%s", (oid, pid))
        if a.email and not c.execute("SELECT 1 FROM people_emails WHERE email=%s", (a.email.lower(),)).fetchone():
            c.execute("INSERT INTO people_emails (person_id, email) VALUES (%s,%s)", (pid, a.email.lower()))
        if a.note:
            c.execute("UPDATE people SET notes = CASE WHEN notes IS NULL THEN %s ELSE notes || E'\\n' || %s END WHERE id=%s", (a.note, a.note, pid))
        if a.touch:
            when = dt.datetime.fromisoformat(a.when) if a.when else dt.datetime.now()
            if a.source and a.source_id and c.execute("SELECT 1 FROM interactions WHERE source=%s AND source_id=%s AND person_id=%s", (a.source, a.source_id, pid)).fetchone():
                print("touch already logged")
            else:
                c.execute("INSERT INTO interactions (person_id, listing_id, channel, direction, occurred_at, summary, by_person_id, source, source_id) "
                          "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (pid, a.deal, a.channel, a.direction, when, a.touch, ben, a.source, a.source_id))
                print(f"touch logged for #{pid}")
        if a.done:
            n = c.execute("UPDATE action_items SET status='done', completed_at=now() WHERE person_id=%s AND status IN ('open','waiting') AND title ILIKE %s",
                          (pid, f"%{a.done}%")).rowcount
            print(f"marked {n} action(s) done")
        if a.action:
            if c.execute("SELECT 1 FROM action_items WHERE person_id=%s AND status IN ('open','waiting') AND lower(title)=lower(%s)", (pid, a.action)).fetchone():
                print("action already open")
            else:
                if len(a.action) > 70:
                    print("warning: title over 70 characters; keep titles short and put context in --details")
                c.execute("INSERT INTO action_items (title, details, owner_person_id, due_on, person_id, listing_id, category, source) VALUES (%s,%s,%s,%s,%s,%s,%s,'log_touch')",
                          (a.action, a.details, ben, a.due, pid, a.deal, a.category))
                print(f"action added for #{pid}")
        c.commit()
    finally:
        c.close()


if __name__ == "__main__":
    main()
