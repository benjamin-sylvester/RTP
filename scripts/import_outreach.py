"""Load an LP outreach list (CSV) into people at stage 'sourced' (migration 026).
See 6.0 Claude/capital/cold-outreach-playbook-v01.md.

  python scripts/import_outreach.py list.csv [--sandbox] [--dry-run]

CSV header row; only `name` is required:
  name, linkedin_url, title, company, city, state, segment, notes
segment is one of practice_owner, trades_owner, passive_investor, lp_referral, other.

Matches an existing person by LinkedIn URL, then by exact name, and never overwrites a stage
someone is already past. New people get no roles until they reach 'conversation' (log_touch.py
adds lp_prospect then), so cold names stay off the LPs tab.
"""
import csv
import os
import sys

import psycopg
from _conn import connect, load_env

SEGMENTS = {"practice_owner", "trades_owner", "passive_investor", "lp_referral", "other"}


def norm_url(u):
    return (u or "").strip().rstrip("/").lower().replace("http://", "https://").replace("https://linkedin.com", "https://www.linkedin.com")


def main():
    path = sys.argv[1]
    if "--sandbox" in sys.argv:
        load_env(); c = psycopg.connect(os.environ["SANDBOX_DATABASE_URL"])
    else:
        c = connect(autocommit=False)
    dry = "--dry-run" in sys.argv
    added = matched = skipped = 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    try:
        for r in rows:
            r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
            name = r.get("name")
            if not name:
                skipped += 1; continue
            seg = r.get("segment") or None
            if seg and seg not in SEGMENTS:
                print(f"skip {name}: unknown segment {seg}"); skipped += 1; continue
            url = norm_url(r.get("linkedin_url")) or None
            pid = None
            if url:
                hit = c.execute("SELECT id FROM people WHERE lower(rtrim(linkedin_url,'/'))=%s AND merged_into_id IS NULL", (url,)).fetchone()
                pid = hit[0] if hit else None
            if pid is None:
                hit = c.execute("SELECT id FROM people WHERE lower(full_name)=lower(%s) AND merged_into_id IS NULL ORDER BY id LIMIT 1", (name,)).fetchone()
                pid = hit[0] if hit else None
            oid = None
            if r.get("company"):
                hit = c.execute("SELECT id FROM organizations WHERE lower(name)=lower(%s) ORDER BY id LIMIT 1", (r["company"],)).fetchone()
                oid = hit[0] if hit else c.execute("INSERT INTO organizations (name, kind, source) VALUES (%s,'other','outreach_list') RETURNING id",
                                                   (r["company"],)).fetchone()[0]
            if pid is None:
                parts = name.split()
                c.execute("INSERT INTO people (full_name, first_name, last_name, org_id, title, roles, linkedin_url, city, state, notes, "
                          "outreach_segment, outreach_stage, source) VALUES (%s,%s,%s,%s,%s,'{}',%s,%s,%s,%s,%s,'sourced','outreach_list')",
                          (name, parts[0], parts[-1] if len(parts) > 1 else None, oid, r.get("title") or None, url,
                           r.get("city") or None, r.get("state") or None, r.get("notes") or None, seg))
                added += 1
            else:
                c.execute("UPDATE people SET org_id=COALESCE(org_id,%s), title=COALESCE(title,%s), linkedin_url=COALESCE(linkedin_url,%s), "
                          "city=COALESCE(city,%s), state=COALESCE(state,%s), outreach_segment=COALESCE(outreach_segment,%s), "
                          "outreach_stage=COALESCE(outreach_stage,'sourced') WHERE id=%s",
                          (oid, r.get("title") or None, url, r.get("city") or None, r.get("state") or None, seg, pid))
                matched += 1
        if dry:
            c.rollback(); print("dry run, rolled back")
        else:
            c.commit()
    finally:
        c.close()
    print(f"{len(rows)} rows: {added} added, {matched} matched existing people, {skipped} skipped")


if __name__ == "__main__":
    main()
