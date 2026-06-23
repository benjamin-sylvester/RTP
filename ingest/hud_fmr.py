"""Phase 3 step 1 — HUD Fair Market Rents loader -> rent_comps (source 'hud').
Free, no Chrome, no scraping. FY2025 FMRs (HUD USER, 40th-percentile gross rent) by
NH FMR area and bedroom, mapped to the buy-box markets + our NH deal markets. Writes
one rent_comps row per market x unit_type as the MARKET-rent baseline.

When a HUD_API_TOKEN is added to .env, refresh_from_api() can repull current-year FMRs;
until then this curated FY2025 table keeps the stabilized calc fed (no dependency).
"""
import json

FMR_YEAR = 2025

# FY2025 FMR by bedroom (0=studio..4) per NH FMR area (HUD USER).
AREAS = {
    "Manchester, NH HMFA":          {0: 1336, 1: 1485, 2: 1948, 3: 2347, 4: 2583},
    "Nashua, NH HMFA":              {0: 1458, 1: 1621, 2: 2126, 3: 2824, 4: 2999},
    "Portsmouth-Rochester, NH HMFA":{0: 1475, 1: 1517, 2: 1961, 3: 2429, 4: 2749},
    "Merrimack County, NH":         {0: 1120, 1: 1230, 2: 1614, 3: 2132, 4: 2140},
}

# market (lower) -> (area, approx?). approx=True flags a town->area mapping to confirm.
MARKET_AREA = {
    "manchester":  ("Manchester, NH HMFA", False),
    "derry":       ("Manchester, NH HMFA", True),
    "londonderry": ("Manchester, NH HMFA", True),
    "salem":       ("Manchester, NH HMFA", True),
    "nashua":      ("Nashua, NH HMFA", False),
    "dover":       ("Portsmouth-Rochester, NH HMFA", False),
    "rochester":   ("Portsmouth-Rochester, NH HMFA", False),
    "somersworth": ("Portsmouth-Rochester, NH HMFA", False),
    "farmington":  ("Portsmouth-Rochester, NH HMFA", True),   # Strafford Co; approx
    "milton":      ("Portsmouth-Rochester, NH HMFA", True),   # Strafford Co; approx
    "pittsfield":  ("Merrimack County, NH", False),           # our rent-roll deal market
    "allenstown":  ("Merrimack County, NH", False),
}

BEDS_TO_TYPE = {0: "Studio", 1: "1BR", 2: "2BR", 3: "3BR", 4: "4BR"}


def load(conn):
    """Write FY2025 HUD FMRs to rent_comps (source 'hud'); idempotent. Returns count."""
    cur = conn.cursor()
    cur.execute("DELETE FROM rent_comps WHERE source='hud'")
    n = 0
    for market, (area, approx) in MARKET_AREA.items():
        fmr = AREAS[area]
        for beds, rent in fmr.items():
            cur.execute(
                """INSERT INTO rent_comps
                   (market, unit_type, beds, rent, source, observed_date, raw_data)
                   VALUES (%s,%s,%s,%s,'hud', %s, %s::jsonb)""",
                (market.title(), BEDS_TO_TYPE[beds], beds, rent,
                 f"{FMR_YEAR}-01-01",
                 json.dumps({"fmr_area": area, "fmr_year": FMR_YEAR,
                             "percentile": "40th", "approx_area_map": approx})))
            n += 1
    return n
