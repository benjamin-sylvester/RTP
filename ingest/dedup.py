"""Dedup + enrichment — the CLAUDE.md hard rule.
Match an incoming parsed listing against existing rows in 3 tiers:
  (a) external_id/MLS exact
  (b) fuzzy address + same city (fuzzystrmatch levenshtein)
  (c) same city + same units + price OR GSI within 5%  (same deal, different sender)
On match: ENRICH the existing row (fill nulls, never blind-overwrite), upsert
listing_financials, add unit_mix if absent, log every changed field to listing_history.
No duplicate row. On no match: insert a new row routed via the buy box.

Candidate dict (from parsers.ai_extract / structured parser), money in DOLLARS:
  address, city, state, zip, units, asking_price, year_built, building_sf, lot_sf,
  unit_mix[{type,count,avg_rent}], gross_revenue, total_expenses, noi, vacancy_rate,
  broker_name, broker_email, listing_date, external_id, latitude, longitude
"""
import json
import re

from ingest import routing
from ingest.geocode import geocode

PCT = 0.05


def _norm_addr(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


_SUFFIX = (r"\b(st|street|ave|avenue|rd|road|dr|drive|ln|lane|blvd|boulevard|way|"
           r"ct|court|pl|place|ter|terrace|hwy|highway|cir|circle|sq|square)\b")


def _house_num(addr):
    m = re.match(r"\s*(\d+)", addr or "")
    return m.group(1) if m else None


def _street_core(addr):
    """Street name minus house number and type suffix, normalized to alnum.
    '74 Sutton St' and '74 Sutton Street' -> 'sutton'."""
    s = re.sub(r"^\s*\d+[a-zA-Z]?(?:-\d+[a-zA-Z]?)?\s*", "", addr or "")  # drop house #
    s = re.sub(_SUFFIX, "", s.lower())                                     # drop suffix word
    return re.sub(r"[^a-z0-9]", "", s)


def _lev(a, b):
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _cents(usd):
    return None if usd is None else round(float(usd) * 100)


def _within(a, b, pct=PCT):
    if a is None or b is None or a == 0:
        return False
    return abs(a - b) / abs(a) <= pct


def _blank(v):
    return v is None or (isinstance(v, str) and v.strip().lower() in ("", "unknown")) \
        or (isinstance(v, str) and "tbd" in v.lower())


# ---------------------------------------------------------------- matching
def find_match(conn, cand):
    """Return (listing_id, tier, detail) or (None, None, None)."""
    cur = conn.cursor()

    # (a) external_id
    if cand.get("external_id"):
        row = cur.execute(
            "SELECT id FROM listings WHERE external_id = %s",
            (str(cand["external_id"]),)).fetchone()
        if row:
            return row[0], "a:external_id", f"external_id={cand['external_id']}"

    city = (cand.get("city") or "").strip()

    # (b) fuzzy address + city: house number MUST match, then fuzzy-match the
    # street-name core (suffix-normalized). This rejects '383' vs '412 Manchester
    # St' (different buildings) while still matching '74 Sutton St' vs '74 Sutton
    # Street' (same building, suffix variant).
    if cand.get("address") and not _blank(cand["address"]) and city:
        cnum = _house_num(cand["address"])
        ccore = _street_core(cand["address"])
        if cnum and ccore:
            rows = cur.execute(
                "SELECT id, address FROM listings WHERE lower(city)=lower(%s) "
                "AND address IS NOT NULL AND address <> 'Unknown'", (city,)).fetchall()
            best = None
            thr = max(1, round(len(ccore) * 0.2))
            for lid, ex_addr in rows:
                if _house_num(ex_addr) != cnum:
                    continue
                d = _lev(ccore, _street_core(ex_addr))
                if d <= thr and (best is None or d < best[1]):
                    best = (lid, d, ex_addr)
            if best:
                return best[0], "b:fuzzy_address", f"'{best[2]}' core_lev={best[1]}<= {thr}"

    # (c) city + units + price/GSI within 5%. ONLY when at least one side is
    # addressless — two rows with real, DIFFERENT street addresses are different
    # properties (tiers a/b already catch same-address-different-sender). This
    # prevents collapsing e.g. two distinct Fall River 6-units priced within 5%.
    cand_has_addr = bool(cand.get("address")) and not _blank(cand["address"])
    if city and cand.get("units"):
        cand_price = cand.get("asking_price")
        cand_gsi = cand.get("gross_revenue")
        rows = cur.execute(
            """
            SELECT l.id, l.address, l.asking_price, lf.gross_revenue,
                   (l.raw_data->>'in_place_gsi') AS gsi_raw
            FROM listings l LEFT JOIN listing_financials lf ON lf.listing_id = l.id
            WHERE lower(l.city)=lower(%s) AND l.units = %s
            """, (city, int(cand["units"]))).fetchall()
        for lid, ex_addr, ask_cents, gr_cents, gsi_raw in rows:
            if cand_has_addr and ex_addr and not _blank(ex_addr):
                continue  # both have real addresses -> not the tier-(c) case
            ex_price = ask_cents / 100 if ask_cents is not None else None
            ex_gsi = (gr_cents / 100 if gr_cents is not None
                      else (float(gsi_raw) if gsi_raw else None))
            if _within(ex_price, cand_price):
                return lid, "c:units+price", f"price ${cand_price:,.0f}~${ex_price:,.0f}"
            if _within(ex_gsi, cand_gsi):
                return lid, "c:units+gsi", f"GSI ${cand_gsi:,.0f}~${ex_gsi:,.0f}"
    return None, None, None


# ---------------------------------------------------------------- enrichment
# listings columns enriched only when currently NULL/blank, value stored in cents where noted.
_LISTING_COLS = [
    ("address", False), ("zip", False), ("year_built", False),
    ("building_sf", False), ("lot_sf", False), ("units", False),
    ("asking_price", True), ("broker_name", False), ("broker_email", False),
    ("listing_date", False), ("external_id", False),
    ("latitude", False), ("longitude", False),
]
_FIN_COLS = ["gross_revenue", "total_expenses", "noi"]  # cents
_FIN_RAW = ["vacancy_rate"]  # ratio, as-is


def _log(cur, lid, field, old, new):
    cur.execute(
        "INSERT INTO listing_history (listing_id, field, old_value, new_value) "
        "VALUES (%s,%s,%s,%s)",
        (lid, field, None if old is None else str(old), None if new is None else str(new)))


def enrich(conn, lid, cand, source_label=""):
    """Fill nulls on the existing row + financials + unit_mix; log every change."""
    cur = conn.cursor()
    changed = []

    cur_row = cur.execute(
        "SELECT address, zip, year_built, building_sf, lot_sf, units, asking_price, "
        "price_per_unit, broker_name, broker_email, listing_date, external_id, "
        "latitude, longitude FROM listings WHERE id=%s", (lid,)).fetchone()
    cols = ["address", "zip", "year_built", "building_sf", "lot_sf", "units",
            "asking_price", "price_per_unit", "broker_name", "broker_email",
            "listing_date", "external_id", "latitude", "longitude"]
    existing = dict(zip(cols, cur_row))

    updates = {}
    for col, is_money in _LISTING_COLS:
        cand_val = cand.get(col)
        if cand_val is None:
            continue
        stored = _cents(cand_val) if is_money else cand_val
        if _blank(existing[col]):
            updates[col] = stored
            _log(cur, lid, col, existing[col], stored)
            changed.append(col)

    # recompute price_per_unit (cents) if we now have both and it's currently null
    units_final = updates.get("units", existing["units"])
    ask_final = updates.get("asking_price", existing["asking_price"])
    if existing["price_per_unit"] is None and ask_final and units_final:
        ppu = round(ask_final / units_final)
        updates["price_per_unit"] = ppu
        _log(cur, lid, "price_per_unit", None, ppu)
        changed.append("price_per_unit")

    if updates:
        sets = ", ".join(f"{c}=%s" for c in updates)
        cur.execute(f"UPDATE listings SET {sets} WHERE id=%s",
                    (*updates.values(), lid))

    # listing_financials: create or fill nulls
    fin_vals = {c: _cents(cand.get(c)) for c in _FIN_COLS}
    fin_vals.update({c: cand.get(c) for c in _FIN_RAW})
    if any(v is not None for v in fin_vals.values()):
        frow = cur.execute(
            "SELECT gross_revenue, total_expenses, noi, vacancy_rate, confidence "
            "FROM listing_financials WHERE listing_id=%s", (lid,)).fetchone()
        if frow is None:
            cur.execute(
                "INSERT INTO listing_financials (listing_id) VALUES (%s)", (lid,))
            frow = (None, None, None, None, None)
        fcols = ["gross_revenue", "total_expenses", "noi", "vacancy_rate", "confidence"]
        fexist = dict(zip(fcols, frow))
        fupd = {}
        for c in _FIN_COLS + _FIN_RAW:
            if fin_vals[c] is not None and fexist[c] is None:
                fupd[c] = fin_vals[c]
                _log(cur, lid, f"financials.{c}", None, fin_vals[c])
                changed.append(f"financials.{c}")
        # raise confidence: newsletter/broker -> medium if currently null/low
        if fexist["confidence"] in (None, "low"):
            fupd["confidence"] = "medium"
            _log(cur, lid, "financials.confidence", fexist["confidence"], "medium")
            changed.append("financials.confidence")
        fupd["data_source"] = "broker"
        if fupd:
            sets = ", ".join(f"{c}=%s" for c in fupd)
            cur.execute(f"UPDATE listing_financials SET {sets} WHERE listing_id=%s",
                        (*fupd.values(), lid))

    # unit_mix: add only if none exist yet
    if cand.get("unit_mix"):
        has = cur.execute(
            "SELECT count(*) FROM unit_mix WHERE listing_id=%s", (lid,)).fetchone()[0]
        if has == 0:
            for um in cand["unit_mix"]:
                cur.execute(
                    "INSERT INTO unit_mix (listing_id, unit_type, count, avg_rent) "
                    "VALUES (%s,%s,%s,%s)",
                    (lid, um.get("type"), um.get("count"), um.get("avg_rent")))
            _log(cur, lid, "unit_mix", None, f"+{len(cand['unit_mix'])} types")
            changed.append("unit_mix")

    return changed


# ---------------------------------------------------------------- insert
def _usable_address(cand):
    a = cand.get("address")
    return bool(_house_num(a)) and not _blank(a)


def is_orphan(cand):
    """No-orphan rule: neither a usable (house-numbered) address NOR an MLS#.
    Such rows are undedupable and silently breed duplicates."""
    return not _usable_address(cand) and not cand.get("external_id")


def insert_listing(conn, cand, source, raw_email_id=None, session=None):
    cur = conn.cursor()
    lat, lon, method = geocode(cand.get("address"), cand.get("city"),
                               cand.get("state"), session)
    units = cand.get("units")
    ask_cents = _cents(cand.get("asking_price"))
    ppu = round(ask_cents / units) if (ask_cents and units) else None
    if is_orphan(cand):
        status = "needs_review"
        reasons = ["quarantined (no-orphan rule): no usable address and no MLS#"]
    else:
        status, reasons = routing.route(cand.get("state"), cand.get("city"),
                                        units, cand.get("asking_price"))
    raw = {k: cand.get(k) for k in ("unit_mix", "gross_revenue", "noi")}
    raw.update({"geocode_method": method, "routing_reasons": reasons,
                "ingest_source": source})
    cur.execute(
        """
        INSERT INTO listings (external_id, address, city, state, latitude, longitude,
            units, asking_price, price_per_unit, year_built, building_sf, status,
            source, broker_name, broker_email, listing_date, raw_email_id, raw_data, notes)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
        RETURNING id
        """,
        (str(cand["external_id"]) if cand.get("external_id") else None,
         cand.get("address") or "Unknown", cand.get("city") or "Unknown",
         (cand.get("state") or "").strip(), lat, lon, units, ask_cents, ppu,
         cand.get("year_built"), cand.get("building_sf"), status, source,
         cand.get("broker_name"), cand.get("broker_email"), cand.get("listing_date"),
         raw_email_id, json.dumps(raw, default=str), None))
    return cur.fetchone()[0], status


# ---------------------------------------------------------------- packages
_RANGE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s+(.+)$")


def try_link_package(conn, cand):
    """If the candidate is a hyphenated street-RANGE listing (e.g. '377-383 Manchester
    St') whose span covers an existing package's member parcels on the same street/city,
    treat it as the package's combined market listing: set the package ask (+ record the
    MLS#) and do NOT create/enrich a parcel row. Returns a link dict or None."""
    m = _RANGE.match(cand.get("address") or "")
    if not m:
        return None
    lo, hi = sorted((int(m.group(1)), int(m.group(2))))
    street_core = _street_core(m.group(3))
    city = (cand.get("city") or "").strip()
    if not (street_core and city):
        return None
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT package_id, address FROM listings "
        "WHERE package_id IS NOT NULL AND lower(city)=lower(%s)", (city,)).fetchall()
    by_pkg = {}
    for pid, a in rows:
        by_pkg.setdefault(pid, []).append(a)
    for pid, addrs in by_pkg.items():
        nums = [_house_num(a) for a in addrs]
        cores = {_street_core(a) for a in addrs}
        if street_core in cores and nums and all(n and lo <= int(n) <= hi for n in nums):
            ask = _cents(cand.get("asking_price"))
            ext = cand.get("external_id")
            updated = []
            if ask is not None:
                cur.execute(
                    "UPDATE packages SET asking_price=%s WHERE id=%s "
                    "AND asking_price IS DISTINCT FROM %s", (ask, pid, ask))
                if cur.rowcount:
                    updated.append("asking_price")
            if ext:
                cur.execute(
                    "UPDATE packages SET notes = COALESCE(notes,'') || %s "
                    "WHERE id=%s AND (notes IS NULL OR notes NOT LIKE %s)",
                    (f" [combined MLS#{ext}]", pid, f"%MLS#{ext}%"))
            return {"package_id": pid, "updated": updated, "mls": ext}
    return None


# ---------------------------------------------------------------- orchestration
def upsert(conn, cand, source, raw_email_id=None, session=None):
    """Returns dict describing the action taken."""
    link = try_link_package(conn, cand)
    if link:
        return {"action": "linked_package", "listing_id": None,
                "package_id": link["package_id"], "matched_on": f"MLS#{link['mls']}",
                "changed": link["updated"]}
    lid, tier, detail = find_match(conn, cand)
    if lid:
        changed = enrich(conn, lid, cand, source)
        return {"action": "enriched", "listing_id": lid, "tier": tier,
                "matched_on": detail, "changed": changed}
    nid, status = insert_listing(conn, cand, source, raw_email_id, session)
    return {"action": "inserted", "listing_id": nid, "status": status}
