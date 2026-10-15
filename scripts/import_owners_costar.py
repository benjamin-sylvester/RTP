"""Import CoStar owner exports into the database.
Reads XLSX files with property/owner data and applies the scoring rubric from pipeline/sourcing/CLAUDE.md.
Extends the existing owner list from import_owners.py.

Scoring rubric:
  Unit band: 10-12 and 13-20 units +40, 21-30 +25, 31-50 +10, 51-100 +0
  Target corridor (C1 I-93 or C2 Strafford County) +15
  Out-of-state owner +20
  Has phone +15
  Owned 10+ years +10
  Tiers: T1 >= 75, T2 55-74, T3 35-54, T4 < 35

Exclusions: no-phone, UNKNOWN owners, affordable/subsidized, government, non-NH, duplicates

Usage:
  python scripts/import_owners_costar.py <xlsx_file> [<xlsx_file2> ...] [--sandbox] [--commit]
"""
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl
import psycopg

from _conn import connect, load_env, ROOT

ENTITY_RE = re.compile(r"\b(llc|l\.l\.c|inc\b|inc\.|trust|properties|property|realty|holdings|partners|"
                       r"associates|group|corp|company|co\.|capital|investments|management|lp\b|ltd|"
                       r"apartments|development|enterprises|ventures|estates|homes)", re.I)

# Target corridors
CORRIDORS = {
    "manchester": "C1",
    "nashua": "C1",
    "derry": "C1",
    "londonderry": "C1",
    "salem": "C1",
    "dover": "C2",
    "rochester": "C2",
    "somersworth": "C2",
    "farmington": "C2",
}


def conn_for(argv):
    if "--sandbox" in argv:
        load_env()
        return psycopg.connect(os.environ["SANDBOX_DATABASE_URL"], autocommit=False)
    return connect(autocommit=False)


def score_owner(row_dict):
    """Apply the scoring rubric to a CoStar export row.
    Returns (score, tier, corridor) or (None, None, None) if excluded."""

    # Exclusions
    owner = (row_dict.get("Owner") or "").strip()
    if not owner or owner.upper() == "UNKNOWN":
        return None, None, None

    # State check (NH only)
    state = (row_dict.get("State") or "").strip().upper()
    if state != "NH":
        return None, None, None

    # Property type: exclude affordable/subsidized/government
    prop_type = (row_dict.get("Property Type") or "").lower()
    if any(x in prop_type for x in ["affordable", "subsidized", "government", "housing authority", "authority"]):
        return None, None, None

    phone = (row_dict.get("Phone") or "").strip()
    if not phone:
        return None, None, None

    score = 0

    # Unit band
    units = None
    units_str = row_dict.get("Units")
    if units_str:
        try:
            units = int(units_str)
            if 10 <= units <= 12 or 13 <= units <= 20:
                score += 40
            elif 21 <= units <= 30:
                score += 25
            elif 31 <= units <= 50:
                score += 10
            elif units > 50:
                score += 0  # 51-100 and above = 0
        except (ValueError, TypeError):
            pass

    # Corridor
    city = (row_dict.get("City") or "").strip().lower()
    corridor = CORRIDORS.get(city)
    if corridor:
        score += 15

    # Out-of-state owner
    owner_state = (row_dict.get("Owner State") or "").strip().upper()
    if owner_state and owner_state != "NH":
        score += 20

    # Has phone (already checked above)
    if phone:
        score += 15

    # Owned 10+ years
    year_acquired = row_dict.get("Year Acquired")
    if year_acquired:
        try:
            year = int(year_acquired)
            if datetime.now().year - year >= 10:
                score += 10
        except (ValueError, TypeError):
            pass

    # Determine tier
    if score >= 75:
        tier = "T1"
    elif 55 <= score <= 74:
        tier = "T2"
    elif 35 <= score <= 54:
        tier = "T3"
    else:
        tier = "T4"

    return score, tier, corridor


def load_costar_xlsx(filepath):
    """Load a CoStar export XLSX file and return a list of dicts."""
    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb.active

    rows = []
    header = None
    for row_idx, row in enumerate(ws.iter_rows(values_only=True), 1):
        if row_idx == 1:
            header = [str(h).strip() if h else "" for h in row]
            continue

        if not any(row):  # Skip empty rows
            continue

        row_dict = {header[i]: row[i] for i in range(min(len(header), len(row)))}
        rows.append(row_dict)

    return rows


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/import_owners_costar.py <xlsx_file> [<xlsx_file2> ...] [--sandbox] [--commit]")
        sys.exit(1)

    files = [f for f in sys.argv[1:] if not f.startswith("--") and f.endswith(".xlsx")]
    if not files:
        print("ERROR: No .xlsx files provided")
        sys.exit(1)

    c = conn_for(sys.argv)

    all_rows = []
    for filepath in files:
        if not os.path.exists(filepath):
            print(f"WARNING: File not found: {filepath}")
            continue
        print(f"Loading {filepath}...")
        rows = load_costar_xlsx(filepath)
        print(f"  Found {len(rows)} rows")
        all_rows.extend(rows)

    # Deduplicate by (owner, address, city)
    seen = set()
    unique_rows = []
    for row in all_rows:
        owner = (row.get("Owner") or "").strip().lower()
        address = (row.get("Address") or "").strip().lower()
        city = (row.get("City") or "").strip().lower()
        key = (owner, address, city)
        if key not in seen:
            seen.add(key)
            unique_rows.append(row)

    print(f"After dedup: {len(unique_rows)} rows")

    # Score and import
    n = {"org": 0, "person": 0, "property": 0, "skipped": 0}
    for row in unique_rows:
        score, tier, corridor = score_owner(row)
        if score is None:
            n["skipped"] += 1
            continue

        owner = (row.get("Owner") or "").strip()
        address = (row.get("Address") or "").strip()
        city = (row.get("City") or "").strip()
        state = (row.get("State") or "").strip() or "NH"
        phone = (row.get("Phone") or "").strip()
        units = row.get("Units")
        year_built = row.get("Year Built")
        owner_state = (row.get("Owner State") or "").strip()

        # Org
        oid = None
        if ENTITY_RE.search(owner):
            r = c.execute("SELECT id FROM organizations WHERE lower(name)=lower(%s) AND kind='owner_entity'",
                         (owner,)).fetchone()
            if r:
                oid = r[0]
            else:
                oid = c.execute(
                    "INSERT INTO organizations (name, kind, city, state, source, notes) "
                    "VALUES (%s,'owner_entity',%s,%s,'costar_export',%s) RETURNING id",
                    (owner, None, owner_state or None, f"Score {score}, Tier {tier}")
                ).fetchone()[0]
                n["org"] += 1

        # Person
        pid = None
        person_name = owner if oid else ""
        if person_name:
            r = c.execute(
                "SELECT id FROM people WHERE lower(full_name)=lower(%s) AND phone=%s AND merged_into_id IS NULL LIMIT 1",
                (person_name, phone)
            ).fetchone()
            if r:
                pid = r[0]
                c.execute("UPDATE people SET roles=(SELECT array_agg(DISTINCT x) FROM unnest(roles || ARRAY['owner']::text[]) x), "
                         "owner_score=GREATEST(COALESCE(owner_score,0), %s), owner_tier=COALESCE(owner_tier,%s), "
                         "phone=COALESCE(phone,%s) WHERE id=%s",
                         (score, tier, phone, pid))
            else:
                parts = person_name.split()
                pid = c.execute(
                    "INSERT INTO people (full_name, first_name, last_name, org_id, roles, phone, city, state, "
                    "owner_score, owner_tier, source) "
                    "VALUES (%s,%s,%s,%s,ARRAY['owner'],%s,%s,%s,%s,%s,'costar_export') RETURNING id",
                    (person_name, parts[0], parts[-1] if len(parts) > 1 else None, oid, phone,
                     None, owner_state or None, score, tier)
                ).fetchone()[0]
                n["person"] += 1

        # Property
        if address and city:
            r = c.execute("SELECT id FROM properties WHERE address_key = rtp_normalize_address(%s,%s,%s)",
                         (address, city, state)).fetchone()
            units_int = None
            try:
                units_int = int(units) if units else None
            except (ValueError, TypeError):
                pass

            year_built_int = None
            try:
                year_built_int = int(year_built) if year_built else None
            except (ValueError, TypeError):
                pass

            note = f"CoStar: score {score}, tier {tier}, corridor {corridor or 'none'}"

            if r:
                prop_id = r[0]
                c.execute("UPDATE properties SET owner_of_record=COALESCE(owner_of_record,%s), "
                         "owner_org_id=COALESCE(owner_org_id,%s), "
                         "units=COALESCE(units,%s), year_built=COALESCE(year_built,%s), "
                         "notes=CASE WHEN notes IS NULL THEN %s WHEN position('CoStar' in notes)>0 THEN notes "
                         "ELSE notes||E'\\n'||%s END WHERE id=%s",
                         (owner or None, oid, units_int, year_built_int, note, note, prop_id))
            else:
                c.execute(
                    "INSERT INTO properties (address, city, state, units, year_built, owner_of_record, "
                    "owner_org_id, notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (address, city, state, units_int, year_built_int, owner or None, oid, note)
                )
                n["property"] += 1

    print("Imported:")
    print(f"  Organizations: {n['org']}")
    print(f"  People: {n['person']}")
    print(f"  Properties: {n['property']}")
    print(f"  Skipped (excluded): {n['skipped']}")
    print("Total owners:", c.execute("SELECT count(*) FROM people WHERE 'owner' = ANY(roles)").fetchone()[0])
    print("By tier:", c.execute("SELECT owner_tier, count(*) FROM people WHERE 'owner' = ANY(roles) GROUP BY 1 ORDER BY 1").fetchall())

    if "--commit" in sys.argv:
        c.commit()
        print("COMMITTED")
    else:
        c.rollback()
        print("DRY-RUN, rolled back")


if __name__ == "__main__":
    main()
