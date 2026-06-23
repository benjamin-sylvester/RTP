"""Phase 2 auto-underwriting: a quick TRIAGE screen, not a verdict.
Computes buy-box flags + quick metrics per deal (on v_deals, package-aware),
builds an explainable composite score (component breakdown + what could NOT be
assessed), a coarse tier (Priority/Watch/Pass), and a score_confidence. Never
auto-rejects: tier Pass = lower in queue, still surfaced.

All thresholds/assumptions/weights come from config/buy_box.yaml (never hardcoded).
rent_comps is empty (Phase 3), so stabilized cap / rent upside / IRR are left null
and excluded; weights renormalize over the components actually available.
"""
import json
import re

from ingest import routing

MARKET_SOURCES = ("hud", "zillow", "costar")  # market-asking; NEVER 'rent_roll'

PRIORITY_MIN = 65   # tier cutoffs (calibrated in step 5)
WATCH_MIN = 45
# Out-of-box deals are comps, not pipeline priorities — gate their triage score so a
# well-penciling out-of-geography deal still sinks below in-box leads. (Never a reject;
# they remain in the DB as comps and keep their full component breakdown.)
OUT_OF_BOX_SCORE_FACTOR = 0.3


# ---------- finance helpers ----------
def mortgage_payment(principal, annual_rate, years):
    r = annual_rate / 12.0
    n = years * 12
    if r == 0:
        return principal / n
    return principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


# ---------- component score maps (0..1) ----------
def cap_score(cap):           # 5% -> 0, 8.5% -> 1
    return _clamp((cap - 0.05) / 0.035)


def ppu_score(ratio):         # ratio = (ppu-median)/median; below market is better
    return _clamp(0.5 - ratio * 2.5)


def dscr_score(dscr):         # 1.0 -> 0, 1.5 -> 1
    return _clamp((dscr - 1.0) / 0.5)


def units_score(u):           # peak 12-20 (from buy_box preference)
    if u is None:
        return None
    if 12 <= u <= 20:
        return 1.0
    if u < 12:
        return _clamp(0.3 + (u - 4) / 8 * 0.7)
    return _clamp(1.0 - (u - 20) / 14 * 0.5)


def dom_score(dom):           # longer on market = more negotiating leverage (mild)
    return _clamp(dom / 120.0)


def rent_upside_score(pct):   # 0% -> 0, 40%+ below-market upside -> 1
    return _clamp(pct / 0.40)


def beds_from_type(s):
    if not s:
        return None
    if "studio" in s.lower():
        return 0
    m = re.search(r"\d+", s)
    return int(m.group()) if m else None


def market_rent(conn, market, beds):
    """Median market-source (hud/zillow/costar) rent for a market + bedroom count."""
    if beds is None:
        return None
    r = conn.execute(
        f"SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY rent) FROM rent_comps "
        f"WHERE source = ANY(%s) AND lower(market)=lower(%s) AND beds=%s",
        (list(MARKET_SOURCES), market, beds)).fetchone()
    return float(r[0]) if r and r[0] is not None else None


def resolve_unit_mix(conn, deal):
    """Return ({beds: count}, source) from unit_mix table, then rent-roll comps,
    then the raw_data unit_mix string. None if undeterminable."""
    if deal["deal_kind"] != "listing":
        return None, None
    lid = deal["deal_id"]
    mix = {}
    for ut, cnt in conn.execute(
            "SELECT unit_type, count FROM unit_mix WHERE listing_id=%s", (lid,)).fetchall():
        b = beds_from_type(ut)
        if b is not None and cnt:
            mix[b] = mix.get(b, 0) + cnt
    if mix:
        return mix, "unit_mix"
    rr = conn.execute(
        "SELECT beds, count(*) FROM rent_comps WHERE source_listing_id=%s AND "
        "source='rent_roll' AND beds IS NOT NULL GROUP BY beds", (lid,)).fetchall()
    if rr:
        mix = {b: c for b, c in rr}
        units = deal.get("effective_units")
        if units and len(mix) == 1 and sum(mix.values()) < units:
            mix[next(iter(mix))] = units  # all one type; fill vacants to total
        return mix, "rent_roll"
    raw = conn.execute("SELECT raw_data->>'unit_mix' FROM listings WHERE id=%s",
                       (lid,)).fetchone()
    if raw and raw[0]:
        for cnt, beds in re.findall(r"(\d+)\s*x\s*(\d+)\s*BR", raw[0], re.I):
            mix[int(beds)] = mix.get(int(beds), 0) + int(cnt)
        if mix:
            return mix, "raw_unit_mix"
    return None, None


def in_place(conn, deal, units):
    """Return (annual_gross_dollars, unit_count) for in-place rent, or (None, None).
    Sources: rent-roll comps (occupied), then raw_data GSI, then financials GSR."""
    if deal["deal_kind"] == "listing":
        rr = conn.execute(
            "SELECT sum(rent), count(*) FROM rent_comps WHERE source_listing_id=%s "
            "AND source='rent_roll'", (deal["deal_id"],)).fetchone()
        if rr and rr[0]:
            return float(rr[0]) * 12, rr[1]
        g = conn.execute("SELECT raw_data->>'in_place_gsi' FROM listings WHERE id=%s",
                         (deal["deal_id"],)).fetchone()
        if g and g[0]:
            return float(g[0]), units
    return None, None


def irr_5yr(equity, annual_cf, net_sale):
    """Rough 5-yr levered IRR via bisection over [-equity, cf, cf, cf, cf, cf+sale]."""
    flows = [-equity, annual_cf, annual_cf, annual_cf, annual_cf, annual_cf + net_sale]
    def npv(r):
        return sum(f / (1 + r) ** i for i, f in enumerate(flows))
    lo, hi = -0.9, 2.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if npv(mid) > 0:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 4)


def stabilized_block(conn, deal, units, ask, A):
    """Compute (cap_stabilized, rent_upside_pct, irr_5yr, detail) from MARKET rents +
    resolved unit mix. Returns all-None if mix or market rents unavailable."""
    mix, mix_src = resolve_unit_mix(conn, deal)
    if not (mix and ask and units):
        return None, None, None, None, None
    mrents = {b: market_rent(conn, deal["market"], b) for b in mix}
    if not all(mrents[b] for b in mix):
        return None, None, None, None, None
    covered = sum(mix.values())
    gsr = sum(mix[b] * mrents[b] * 12 for b in mix)
    if covered < units:                       # fill remaining units at the mix avg
        gsr += (gsr / covered) * (units - covered)
    stab_noi = gsr * A["stabilized_occupancy"] * (1 - A["expense_ratio_default"])
    cap_stab = stab_noi / ask

    upside = None
    ip_gross, ip_units = in_place(conn, deal, units)
    if ip_gross and ip_units:
        mkt_pu = gsr / units
        ip_pu = ip_gross / ip_units
        if ip_pu > 0:
            upside = (mkt_pu - ip_pu) / ip_pu

    # rough 5-yr IRR
    loan = ask * A["ltv"]
    equity = ask - loan + A["reno_per_unit_usd"] * units
    ads = mortgage_payment(loan, A["interest_rate"], A["amortization_years"]) * 12
    annual_cf = stab_noi - ads
    exit_cap = max(0.04, cap_stab - A["exit_cap_compression_bps"] / 10000)
    net_sale = stab_noi / exit_cap - loan
    irr = irr_5yr(equity, annual_cf, net_sale)

    detail = (f"stab cap {cap_stab*100:.1f}% on market rents ({mix_src} mix), "
              + (f"upside {upside*100:+.0f}%" if upside is not None else "upside n/a"))
    return cap_stab, upside, irr, detail, mix_src


# ---------- financials ----------
def deal_financials(conn, deal_kind, deal_id):
    """Return (in_place_gsi_usd, verified_noi_usd).
    verified_noi is set ONLY from a real T-12 (data_source 't12') — a broker's
    headline NOI is NEVER returned, so it can't inflate the current cap (the Nashua
    trap). GSI prefers rent-roll-verified in-place income, then broker GSR, then raw."""
    if deal_kind == "package":
        row = conn.execute(
            "SELECT SUM(lf.gross_revenue) FROM listing_financials lf "
            "JOIN listings l ON l.id=lf.listing_id WHERE l.package_id=%s", (deal_id,)
        ).fetchone()
        gsi = float(row[0]) / 100 if row and row[0] is not None else None
        return gsi, None
    rr = conn.execute(
        "SELECT sum(rent) FROM rent_comps WHERE source_listing_id=%s AND source='rent_roll'",
        (deal_id,)).fetchone()
    rr_gsi = float(rr[0]) * 12 if rr and rr[0] else None
    lf = conn.execute(
        "SELECT gross_revenue, noi, data_source FROM listing_financials WHERE listing_id=%s",
        (deal_id,)).fetchone()
    lf_gsi = float(lf[0]) / 100 if lf and lf[0] is not None else None
    verified_noi = float(lf[1]) / 100 if (lf and lf[1] is not None and lf[2] == "t12") else None
    rg = conn.execute("SELECT raw_data->>'in_place_gsi' FROM listings WHERE id=%s",
                      (deal_id,)).fetchone()
    raw_gsi = float(rg[0]) if rg and rg[0] else None
    return (rr_gsi or lf_gsi or raw_gsi), verified_noi


def city_median_ppu(conn, city, exclude_id):
    rows = conn.execute(
        "SELECT price_per_unit FROM listings "
        "WHERE lower(city)=lower(%s) AND price_per_unit IS NOT NULL AND id<>%s",
        (city, exclude_id or -1)).fetchall()
    vals = sorted(r[0] for r in rows)
    if len(vals) < 2:
        return None, len(vals)
    n = len(vals)
    mid = n // 2
    med = vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2
    return med / 100, n  # dollars


# ---------- buy-box flags ----------
def buy_box_flags(state, city, units, price_usd, year_built, prop_class):
    bb = routing.buy_box()
    flags, fails = {}, 0
    st_ok = (state or "").strip().upper() == bb["geography"]["state"]
    flags["geography"] = {"pass": st_ok, "value": state,
                          "in_corridor": (city or "").lower() in routing.corridor_markets()}
    u_ok = units is not None and bb["units"]["min"] <= units <= bb["units"]["max"]
    flags["units"] = {"pass": u_ok, "value": units,
                      "range": [bb["units"]["min"], bb["units"]["max"]]}
    p_ok = price_usd is not None and bb["price"]["min_usd"] <= price_usd <= bb["price"]["max_usd"]
    flags["price"] = {"pass": p_ok, "value": price_usd}
    yb_ok = year_built is None or year_built >= bb["year_built"]["min"]
    flags["year_built"] = {"pass": yb_ok, "value": year_built, "unknown": year_built is None}
    cls_ok = prop_class is None or prop_class in bb["property_class"]
    flags["property_class"] = {"pass": cls_ok, "value": prop_class, "unknown": prop_class is None}
    meets = st_ok and u_ok and p_ok and yb_ok and cls_ok
    return meets, flags


# ---------- main per-deal compute ----------
def compute(conn, deal):
    """deal = dict(deal_kind, deal_id, name, market, state, status, effective_units,
    effective_ask_cents, year_built, property_class). Returns the full au row dict."""
    bb = routing.buy_box()
    A = bb["assumptions"]
    W = bb["scoring_weights"]
    units = int(deal["effective_units"]) if deal["effective_units"] is not None else None
    ask = float(deal["effective_ask_cents"]) / 100 if deal["effective_ask_cents"] else None
    city = deal["market"]

    meets, flags = buy_box_flags(deal["state"], city, units, ask,
                                 deal.get("year_built"), deal.get("property_class"))

    gsi, verified_noi = deal_financials(conn, deal["deal_kind"], deal["deal_id"])
    # Normalized NOI for current cap + DSCR: verified T-12 actuals, else GSI x default
    # expense ratio. NEVER the broker's headline NOI (keeps a rosy expense ratio from
    # inflating the score — the Nashua trap).
    if verified_noi is not None:
        noi_norm, noi_basis = verified_noi, "T-12 verified"
    elif gsi is not None:
        noi_norm, noi_basis = gsi * (1 - A["expense_ratio_default"]), "normalized expense ratio"
    else:
        noi_norm, noi_basis = None, None

    metrics, components, unassessed = {}, {}, []

    cap_cur = (noi_norm / ask) if (noi_norm and ask) else None
    metrics["implied_cap_current"] = cap_cur
    # Phase 3: stabilized cap + rent upside from MARKET rents (hud/zillow), if mix known.
    cap_stab, rent_upside, irr, stab_detail, mix_src = stabilized_block(conn, deal, units, ask, A)

    # Two independent cap components (weights from buy_box.yaml): stabilized = value-add
    # return at market rents; current = normalized cash flow today.
    if cap_stab is not None:
        components["cap_stabilized"] = (W["cap_rate_stabilized"], cap_score(cap_stab), stab_detail)
    else:
        unassessed.append("stabilized cap (need market rents + unit mix)")
    if cap_cur is not None:
        components["cap_current"] = (W["cap_rate_current"], cap_score(cap_cur),
                                     f"current cap {cap_cur*100:.1f}% ({noi_basis})")
    else:
        unassessed.append("current cap (no in-place income)")

    if rent_upside is not None:
        components["rent_upside"] = (W["rent_upside_pct"], rent_upside_score(rent_upside),
                                     f"rent upside {rent_upside*100:+.0f}% (market vs in-place)")
    else:
        unassessed.append("rent_upside (need market rents + in-place)")

    # PPU vs market
    ppu_vs = None
    if ask and units:
        ppu = ask / units
        med, ncomp = city_median_ppu(conn, city, deal["deal_id"] if deal["deal_kind"] == "listing" else None)
        if med:
            ppu_vs = (ppu - med) / med
            metrics["price_per_unit_vs_market"] = ppu_vs
            components["ppu"] = (W["price_per_unit_vs_market"], ppu_score(ppu_vs),
                                 f"PPU ${ppu:,.0f} vs {city} median ${med:,.0f} "
                                 f"({ppu_vs*100:+.0f}%, n={ncomp})")
        else:
            unassessed.append(f"PPU-vs-market (<2 comps in {city})")

    # DSCR — on the SAME normalized NOI (never the broker's headline NOI)
    dscr = None
    if noi_norm and ask:
        loan = ask * A["ltv"]
        ads = mortgage_payment(loan, A["interest_rate"], A["amortization_years"]) * 12
        dscr = noi_norm / ads if ads else None
        metrics["estimated_dscr"] = dscr
        components["dscr"] = (W["dscr"], dscr_score(dscr),
                              f"DSCR {dscr:.2f} @ {A['interest_rate']*100:.2f}% "
                              f"(floor {A['dscr_floor']}, {noi_basis})")
        flags["dscr_below_floor"] = dscr < A["dscr_floor"]
    else:
        unassessed.append("DSCR (no in-place income)")

    # unit sweet spot
    us = units_score(units)
    if us is not None:
        components["units"] = (W["unit_count_sweet_spot"], us, f"{units} units")
    else:
        unassessed.append("unit sweet-spot (units unknown)")

    # days on market
    dom = conn.execute("SELECT days_on_market FROM listings WHERE id=%s",
                       (deal["deal_id"],)).fetchone() if deal["deal_kind"] == "listing" else None
    dom = dom[0] if dom else None
    if dom is not None:
        components["dom"] = (W["days_on_market"], dom_score(dom), f"{dom} days on market")
    else:
        unassessed.append("days-on-market (not provided)")

    # composite, renormalized over available components
    wsum = sum(w for w, _, _ in components.values())
    component_score = round(100 * sum(w * s for w, s, _ in components.values()) / wsum) if wsum else None
    # buy-box gate: out-of-box deals (comps) are scaled down so they sink below leads.
    score = component_score
    if score is not None and not meets:
        score = round(score * OUT_OF_BOX_SCORE_FACTOR)

    breakdown = {k: {"weight": w, "score": round(s, 3),
                     "contribution": round(100 * w * s / wsum, 1) if wsum else None,
                     "detail": d}
                 for k, (w, s, d) in components.items()}

    # confidence: high = VERIFIED NOI (T-12) + market rents; medium = one; low = neither.
    # A broker's headline NOI is never "verified", so it can't earn high confidence.
    has_market = cap_stab is not None
    verified = verified_noi is not None
    if verified and has_market:
        confidence = "high"
    elif verified or has_market:
        confidence = "medium"
    else:
        confidence = "low"

    # tier — never discards; out-of-box or weak just sinks in the queue
    if score is None:
        tier = "Pass"
    elif not meets:
        tier = "Pass"
    elif score >= PRIORITY_MIN:
        tier = "Priority"
    elif score >= WATCH_MIN:
        tier = "Watch"
    else:
        tier = "Pass"

    flags["_score_breakdown"] = breakdown
    flags["_not_assessed"] = unassessed
    flags["_renorm_weight_base"] = round(wsum, 3)
    flags["_component_score"] = component_score   # pre-gate quality (before buy-box gate)
    if score != component_score:
        flags["_out_of_box_gate"] = OUT_OF_BOX_SCORE_FACTOR

    return {
        "meets_buy_box": meets,
        "buy_box_flags": flags,
        "implied_cap_current": cap_cur,
        "implied_cap_stabilized": cap_stab,
        "price_per_unit_vs_market": ppu_vs,
        "rent_upside_pct": rent_upside,
        "estimated_dscr": dscr,
        "estimated_irr_5yr": irr,
        "score": score,
        "score_confidence": confidence,
        "tier": tier,
    }


def write(conn, deal, au, summary=None):
    key_col = "package_id" if deal["deal_kind"] == "package" else "listing_id"
    if summary is None:  # preserve an existing AI summary across metric re-runs
        prev = conn.execute(
            f"SELECT summary FROM auto_underwriting WHERE {key_col}=%s", (deal["deal_id"],)
        ).fetchone()
        summary = prev[0] if prev else None
    conn.execute(f"DELETE FROM auto_underwriting WHERE {key_col}=%s", (deal["deal_id"],))
    conn.execute(
        f"""INSERT INTO auto_underwriting
        ({key_col}, meets_buy_box, buy_box_flags, implied_cap_current,
         implied_cap_stabilized, price_per_unit_vs_market, rent_upside_pct,
         estimated_dscr, estimated_irr_5yr, score, score_confidence, tier, summary)
        VALUES (%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (deal["deal_id"], au["meets_buy_box"], json.dumps(au["buy_box_flags"], default=str),
         au["implied_cap_current"], au["implied_cap_stabilized"],
         au["price_per_unit_vs_market"], au["rent_upside_pct"], au["estimated_dscr"],
         au["estimated_irr_5yr"], au["score"], au["score_confidence"], au["tier"],
         summary))
