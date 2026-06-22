"""Phase 0.3 — seed listings from RTP_Deal_Database.xlsx.
- Money stored in cents (asking_price, price_per_unit).
- Status routed from config/buy_box.yaml (single source of truth).
- Geocode via free Census geocoder; city-centroid fallback for 'Unknown' streets.
Idempotent: truncates listings (cascade) and reseeds. Safe in Phase 0 (no live data).
"""
import json
import math
import time
import sys

import pandas as pd
import requests
import yaml

from _conn import connect, ROOT

SEED_FILE = "RTP_Deal_Database.xlsx"
CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"

# City-centroid fallback (decimal degrees) for rows whose street is 'Unknown'.
# Used only when Census returns no match; method is logged per row.
CITY_CENTROIDS = {
    ("manchester", "NH"): (42.9956, -71.4548),
    ("pittsfield", "NH"): (43.3037, -71.3242),
    ("allenstown", "NH"): (43.1465, -71.4090),
}


def load_buy_box():
    return yaml.safe_load((ROOT / "config" / "buy_box.yaml").read_text())


def corridor_markets(bb):
    out = set()
    for c in bb["geography"]["corridors"]:
        out.update(m.lower() for m in c["markets"])
    return out


def route_status(row, bb, markets):
    """Return (status, reasons). buy-box fit or borderline -> lead, else comp_only."""
    reasons = []
    state = (row["state"] or "").strip().upper()
    if state != bb["geography"]["state"]:
        return "comp_only", [f"state {state or '?'} outside {bb['geography']['state']}"]

    units = row["units"]
    umin, umax = bb["units"]["min"], bb["units"]["max"]
    units_ok = units is not None and umin <= units <= umax
    if not units_ok:
        reasons.append(f"units {units} outside {umin}-{umax}")

    price = row["price_dollars"]
    pmin, pmax = bb["price"]["min_usd"], bb["price"]["max_usd"]
    price_ok = price is None or (pmin <= price <= pmax)  # unknown price doesn't fail
    if price is not None and not price_ok:
        reasons.append(f"price ${price:,.0f} outside ${pmin:,}-${pmax:,}")

    in_corridor = (row["city"] or "").strip().lower() in markets

    if units_ok and price_ok and in_corridor:
        return "lead", ["NH + in-corridor + size/price fit"]
    if units_ok and price_ok and not in_corridor:
        return "lead", ["NH, size/price fit, outside named corridors -> borderline"]
    return "comp_only", reasons or ["does not meet buy box"]


def map_source(raw):
    s = (raw or "").lower()
    if s.startswith("mls"):
        return "mls_export"
    return "broker_email"  # broker, candor newsletter, NE PCG OMs all arrive by email


def geocode(street, city, state, session):
    """Census first; city-centroid fallback for 'Unknown' streets. Returns (lat, lon, method)."""
    street_known = street and street.strip().lower() != "unknown"
    query = f"{street}, {city}, {state}" if street_known else f"{city}, {state}"
    try:
        r = session.get(CENSUS_URL, params={
            "address": query, "benchmark": "Public_AR_Current", "format": "json",
        }, timeout=20)
        r.raise_for_status()
        matches = r.json().get("result", {}).get("addressMatches", [])
        if matches:
            c = matches[0]["coordinates"]
            return round(c["y"], 6), round(c["x"], 6), "census"
    except Exception as e:
        print(f"    census error for '{query}': {e}")
    fb = CITY_CENTROIDS.get((city.strip().lower(), state.strip().upper()))
    if fb:
        return fb[0], fb[1], "city_centroid_fallback"
    return None, None, "none"


def clean(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def main():
    bb = load_buy_box()
    markets = corridor_markets(bb)

    df = pd.read_excel(ROOT / SEED_FILE, sheet_name="Deal Database", header=4)
    df = df.dropna(how="all")
    df = df[df["Address"].notna() | df["City"].notna()]
    print(f"Loaded {len(df)} rows from {SEED_FILE}\n")

    session = requests.Session()
    records = []
    for _, r in df.iterrows():
        units = clean(r.get("Units"))
        units = int(units) if units is not None else None
        price_d = clean(r.get("Asking Price"))
        price_d = float(price_d) if price_d is not None else None
        asking_cents = round(price_d * 100) if price_d is not None else None
        ppu_cents = round(asking_cents / units) if (asking_cents and units) else None
        yb = clean(r.get("Year Built"))
        sf = clean(r.get("Sq Ft"))
        date_recv = clean(r.get("Date Received"))

        rec = {
            "external_id": str(int(clean(r.get("MLS #")))) if clean(r.get("MLS #")) is not None else None,
            "address": clean(r.get("Address")) or "Unknown",
            "city": clean(r.get("City")) or "Unknown",
            "state": (clean(r.get("State")) or "").strip(),
            "units": units,
            "price_dollars": price_d,
            "asking_price": asking_cents,
            "price_per_unit": ppu_cents,
            "year_built": int(yb) if yb is not None else None,
            "building_sf": int(sf) if sf is not None else None,
            "source": map_source(clean(r.get("Source"))),
            "broker_name": clean(r.get("Broker/Agent")),
            "broker_email": clean(r.get("Broker Email")),
            "listing_date": pd.to_datetime(date_recv).date() if date_recv is not None else None,
            "raw_email_id": clean(r.get("Email Thread ID")),
            "notes": clean(r.get("Notes")),
            "raw_data": {
                "source_label": clean(r.get("Source")),
                "unit_mix": clean(r.get("Unit Mix")),
                "property_type": clean(r.get("Property Type")),
                "buy_box_fit_sheet": clean(r.get("Buy Box Fit")),
                "listed_cap_rate": clean(r.get("Listed Cap Rate")),
                "gross_rent_mo": clean(r.get("Gross Rent (Mo)")),
                "gross_rent_ann": clean(r.get("Gross Rent (Ann)")),
                "price_per_unit_sheet_usd": clean(r.get("Price/Unit")),
                "seed_source": SEED_FILE,
            },
        }
        status, reasons = route_status(rec, bb, markets)
        rec["status"] = status
        rec["raw_data"]["routing_reasons"] = reasons
        records.append(rec)

    # Geocode
    print("Geocoding (Census + centroid fallback)...")
    for rec in records:
        lat, lon, method = geocode(rec["address"], rec["city"], rec["state"], session)
        rec["latitude"], rec["longitude"], rec["geocode_method"] = lat, lon, method
        rec["raw_data"]["geocode_method"] = method
        print(f"  {rec['city']:<12} {rec['address'][:24]:<24} -> "
              f"{(str(lat)+','+str(lon)) if lat else 'NO MATCH':<22} [{method}]")
        time.sleep(0.2)

    # Insert
    with connect(autocommit=False) as conn:
        with conn.cursor() as cur:
            existing = cur.execute("SELECT count(*) FROM listings").fetchone()[0]
            if existing:
                print(f"\nlistings has {existing} rows; truncating for clean reseed.")
            cur.execute("TRUNCATE listings RESTART IDENTITY CASCADE")
            for rec in records:
                cur.execute(
                    """
                    INSERT INTO listings
                      (external_id, address, city, state, latitude, longitude,
                       units, asking_price, price_per_unit, year_built, building_sf,
                       status, source, broker_name, broker_email, listing_date,
                       raw_email_id, raw_data, notes)
                    VALUES
                      (%(external_id)s, %(address)s, %(city)s, %(state)s, %(latitude)s, %(longitude)s,
                       %(units)s, %(asking_price)s, %(price_per_unit)s, %(year_built)s, %(building_sf)s,
                       %(status)s, %(source)s, %(broker_name)s, %(broker_email)s, %(listing_date)s,
                       %(raw_email_id)s, %(raw_data)s, %(notes)s)
                    """,
                    {**rec, "raw_data": json.dumps(rec["raw_data"], default=str)},
                )
        conn.commit()

    leads = sum(1 for r in records if r["status"] == "lead")
    comps = sum(1 for r in records if r["status"] == "comp_only")
    geo = sum(1 for r in records if r["latitude"] is not None)
    print(f"\nInserted {len(records)} listings: {leads} lead, {comps} comp_only. "
          f"Geocoded {geo}/{len(records)}.")


if __name__ == "__main__":
    main()
