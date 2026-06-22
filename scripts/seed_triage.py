"""Phase 0.6 — seed 3 specific NH triage deals as leads.
Core fields are authoritative from Ben's instruction; raw_data enriched from the
triage xlsx matched on Gmail thread id. raw_email_id = thread id so Phase 1
ingestion dedups on thread. Idempotent: skips a deal whose thread already exists.
Money in cents. Geocode via Census + city-centroid fallback (shared module).
"""
import json
import pandas as pd
import requests

from _conn import connect, ROOT
from seed_listings import geocode  # shared Census + centroid geocoder

TRIAGE_FILE = "RTP_DealFlow_Triage_2026-06-22.xlsx"

# (address, city, state, units, asking_dollars, thread_id, listing_date)
DEALS = [
    ("339-341 Amherst St", "Manchester", "NH", 6, 1_350_000, "19edc469c20448dd", "2026-06-18"),
    ("805 Central Ave",    "Dover",      "NH", 4,   800_000, "19edc4628cc30d16", "2026-06-18"),
    ("Nashua 6-unit (addr TBD)", "Nashua", "NH", 6,    None, "19e7064253032ca2", "2026-06-01"),
]


def main():
    # Enrichment from the triage file, keyed by thread id.
    tri = pd.read_excel(ROOT / TRIAGE_FILE, sheet_name="Deal Flow Log").dropna(how="all")
    by_thread = {str(r["Thread ID"]): r for _, r in tri.iterrows() if pd.notna(r.get("Thread ID"))}

    session = requests.Session()
    with connect(autocommit=False) as conn, conn.cursor() as cur:
        inserted, skipped = 0, 0
        for addr, city, state, units, price_d, thread, ldate in DEALS:
            exists = cur.execute(
                "SELECT id, address FROM listings WHERE raw_email_id=%s", (thread,)
            ).fetchone()
            if exists:
                print(f"SKIP (thread {thread} already at listing #{exists[0]} "
                      f"'{exists[1]}'): {addr}")
                skipped += 1
                continue

            asking_cents = round(price_d * 100) if price_d is not None else None
            ppu_cents = round(asking_cents / units) if (asking_cents and units) else None
            lat, lon, method = geocode(addr, city, state, session)

            t = by_thread.get(thread)
            raw = {
                "seed_source": TRIAGE_FILE,
                "source_label": (t.get("Source") if t is not None else "Off-market"),
                "unit_mix": (t.get("Unit Mix") if t is not None else None),
                "in_place_gsi": (t.get("In-Place GSI") if t is not None else None),
                "price_per_unit_sheet_usd": (t.get("$/Unit") if t is not None else None),
                "buy_box_fit_sheet": (t.get("Buy Box") if t is not None else None),
                "geocode_method": method,
                "seeded_as": "lead (per Ben's triage instruction)",
            }
            raw = {k: (None if (isinstance(v, float) and pd.isna(v)) else v) for k, v in raw.items()}
            notes = str(t.get("Notes")) if (t is not None and pd.notna(t.get("Notes"))) else None

            cur.execute(
                """
                INSERT INTO listings
                  (address, city, state, latitude, longitude, units, asking_price,
                   price_per_unit, status, source, broker_name, broker_email,
                   listing_date, raw_email_id, raw_data, notes)
                VALUES
                  (%s,%s,%s,%s,%s,%s,%s,%s,'lead','broker_email',
                   'Justin Porter','justin@portercapitalrei.com',
                   %s,%s,%s::jsonb,%s)
                RETURNING id
                """,
                (addr, city, state, lat, lon, units, asking_cents, ppu_cents,
                 ldate, thread, json.dumps(raw, default=str), notes),
            )
            nid = cur.fetchone()[0]
            ask_s = f"${price_d:,.0f}" if price_d else "ask TBD"
            print(f"INSERT #{nid} lead: {addr}, {city} {state} ({units}u, {ask_s}) "
                  f"thread={thread} geo=[{method}]")
            inserted += 1
        conn.commit()
        print(f"\n{inserted} inserted, {skipped} skipped.")


if __name__ == "__main__":
    main()
