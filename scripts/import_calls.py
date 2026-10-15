"""Import the RTP Call Tracker Google Sheet call log into the interactions table.
Reads the 'Calls' tab and creates interaction rows for each logged call.
Idempotent: uses source='call_sheet' and source_id=<owner_address>|<owner_city> as the dedup key.

Usage:
  python scripts/import_calls.py [--sandbox] [--commit]
"""
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from _conn import connect, load_env, ROOT

# Import TOKEN_URI from ingest module
try:
    from ingest.gmail_client import TOKEN_URI
except ImportError:
    # Fallback if module path is different
    TOKEN_URI = "https://oauth2.googleapis.com/token"

SHEET_ID = "1hUST9foqmihuo1llt9Z6tItVpKD_rvnRY1bNtROY4s0"
SHEET_TAB = "Calls"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

OUTCOME_MAP = {
    "Sell now": "Sell now",
    "sell now": "Sell now",
    "Sell later": "Sell later",
    "sell later": "Sell later",
    "Maybe / warm": "Maybe / warm",
    "maybe": "Maybe / warm",
    "warm": "Maybe / warm",
    "Not selling": "Not selling",
    "not selling": "Not selling",
    "No answer": "No answer",
    "no answer": "No answer",
    "Wrong number": "Wrong number",
    "wrong #": "Wrong number",
    "Wrong #": "Wrong number",
}


def conn_for(argv):
    if "--sandbox" in argv:
        load_env()
        return psycopg.connect(os.environ["SANDBOX_DATABASE_URL"], autocommit=False)
    return connect(autocommit=False)


def sheets_service():
    """Google Sheets client, authed as ben@rtprei.com via the Gmail token."""
    load_env()
    tok = (os.environ.get("GMAIL_REFRESH_TOKEN_RTP")
           or os.environ.get("GMAIL_REFRESH_TOKEN"))
    creds = Credentials(
        None,
        refresh_token=tok,
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        token_uri=TOKEN_URI,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def load_calls():
    """Read the Calls tab from the RTP Call Tracker sheet."""
    svc = sheets_service()
    result = svc.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"{SHEET_TAB}!A1:Z1000",
    ).execute()
    values = result.get("values", [])
    if not values:
        return []

    # Row 0 is header. Find columns by name.
    header = [h.strip() if h else "" for h in values[0]]
    try:
        owner_idx = header.index("Owner")
        city_idx = header.index("City")
        status_idx = header.index("Status")
        outcome_idx = header.index("Outcome")
        called_by_idx = header.index("Called By")
        call_date_idx = header.index("Call Date")
        notes_idx = header.index("Notes")
    except ValueError as e:
        print(f"ERROR: Column not found in header: {e}. Header is: {header}")
        return []

    calls = []
    for row_idx, row in enumerate(values[1:], 1):
        # Pad row to ensure we have enough columns
        while len(row) <= max(status_idx, outcome_idx, called_by_idx, call_date_idx, notes_idx):
            row.append("")

        owner = (row[owner_idx] or "").strip()
        city = (row[city_idx] or "").strip()
        status = (row[status_idx] or "").strip()  # unused, but logged
        outcome = (row[outcome_idx] or "").strip()
        called_by = (row[called_by_idx] or "").strip()
        call_date_str = (row[call_date_idx] or "").strip()
        notes = (row[notes_idx] or "").strip()

        # Skip rows with no outcome
        if not outcome or not owner or not city:
            continue

        # Parse call date (expect MM/DD/YYYY)
        call_date = None
        if call_date_str:
            try:
                call_date = dt.datetime.strptime(call_date_str, "%m/%d/%Y").date()
            except ValueError:
                print(f"WARNING: Could not parse call date '{call_date_str}' on row {row_idx}")
                continue
        else:
            continue  # Skip if no date

        # Map outcome to standardized text
        outcome_text = OUTCOME_MAP.get(outcome, outcome)

        # Build summary
        summary = f"Cold call outcome: {outcome_text}"
        if notes:
            summary += f". {notes}"

        calls.append({
            "owner": owner,
            "city": city,
            "outcome": outcome_text,
            "called_by": called_by,
            "call_date": call_date,
            "summary": summary,
            "source_id": f"{owner}|{city}",
        })

    return calls


def main():
    c = conn_for(sys.argv)
    calls = load_calls()

    # Get internal people (Ben, Ren) to map called_by to person_id
    ben_id = c.execute("SELECT id FROM people WHERE full_name='Ben Sylvester'").fetchone()
    ren_id = c.execute("SELECT id FROM people WHERE full_name='Ren LaMotte'").fetchone()
    internal = {
        "Ben Sylvester": ben_id[0] if ben_id else None,
        "ben@rtprei.com": ben_id[0] if ben_id else None,
        "Ren LaMotte": ren_id[0] if ren_id else None,
        "ren@rtprei.com": ren_id[0] if ren_id else None,
    }

    n = 0
    for call in calls:
        # Skip if already imported
        if c.execute("SELECT 1 FROM interactions WHERE source='call_sheet' AND source_id=%s",
                     (call["source_id"],)).fetchone():
            continue

        # Find the owner person/org
        owner_person = c.execute(
            "SELECT p.id FROM people p WHERE lower(p.full_name)=lower(%s) AND 'owner' = ANY(p.roles)",
            (call["owner"],)
        ).fetchone()
        person_id = owner_person[0] if owner_person else None

        if not person_id:
            # Try to find by org name
            owner_org = c.execute(
                "SELECT id FROM organizations WHERE lower(name)=lower(%s) AND kind='owner_entity'",
                (call["owner"],)
            ).fetchone()
            org_id = owner_org[0] if owner_org else None
        else:
            org_id = None

        if not person_id and not org_id:
            print(f"WARNING: Owner '{call['owner']}' not found; skipping call")
            continue

        # Find the property by owner + city
        prop = c.execute(
            "SELECT id FROM properties WHERE lower(owner_of_record)=lower(%s) AND lower(city)=lower(%s)",
            (call["owner"], call["city"])
        ).fetchone()
        property_id = prop[0] if prop else None

        # Map called_by to a person_id (or use the owner's caller)
        by_person_id = internal.get(call["called_by"])
        if not by_person_id:
            # Default to Ben if not recognized
            by_person_id = internal.get("Ben Sylvester")

        # Create the interaction
        # Convert call_date to timestamptz (assume 12:00 EST)
        occurred_at = dt.datetime.combine(call["call_date"], dt.time(12, 0))
        occurred_at = occurred_at.replace(tzinfo=dt.timezone(dt.timedelta(hours=-5)))

        c.execute(
            "INSERT INTO interactions (person_id, org_id, property_id, channel, direction, "
            "occurred_at, summary, by_person_id, source, source_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (person_id, org_id, property_id, "call", "outbound", occurred_at,
             call["summary"], by_person_id, "call_sheet", call["source_id"])
        )
        n += 1

    print(f"Imported {n} calls from the RTP Call Tracker sheet")
    print("call log counts:",
          c.execute("SELECT count(*) FROM interactions WHERE source='call_sheet'").fetchone()[0])

    if "--commit" in sys.argv:
        c.commit()
        print("COMMITTED")
    else:
        c.rollback()
        print("DRY-RUN, rolled back")


if __name__ == "__main__":
    main()
