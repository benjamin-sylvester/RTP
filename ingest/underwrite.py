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

from ingest import routing

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


# ---------- financials ----------
def deal_financials(conn, deal_kind, deal_id):
    """Return (noi_usd, noi_is_estimated, gsi_usd) for a listing or package."""
    if deal_kind == "package":
        row = conn.execute(
            "SELECT SUM(lf.noi), SUM(lf.gross_revenue) FROM listing_financials lf "
            "JOIN listings l ON l.id=lf.listing_id WHERE l.package_id=%s", (deal_id,)
        ).fetchone()
        raw_gsi = None
    else:
        row = conn.execute(
            "SELECT noi, gross_revenue FROM listing_financials WHERE listing_id=%s",
            (deal_id,)).fetchone()
        rg = conn.execute(
            "SELECT raw_data->>'in_place_gsi' FROM listings WHERE id=%s", (deal_id,)
        ).fetchone()
        raw_gsi = float(rg[0]) if rg and rg[0] else None
    noi_c, gsi_c = (row or (None, None))
    noi = float(noi_c) / 100 if noi_c is not None else None
    gsi = float(gsi_c) / 100 if gsi_c is not None else raw_gsi
    return noi, gsi


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

    noi, gsi = deal_financials(conn, deal["deal_kind"], deal["deal_id"])
    noi_estimated = False
    if noi is None and gsi is not None:
        noi = gsi * (1 - A["expense_ratio_default"])
        noi_estimated = True

    metrics, components, unassessed = {}, {}, []

    # implied cap (current). Stabilized excluded (no rent_comps) -> degrade to current.
    cap_cur = (noi / ask) if (noi and ask) else None
    metrics["implied_cap_current"] = cap_cur
    if cap_cur is not None:
        components["cap"] = (W["cap_rate_stabilized"], cap_score(cap_cur),
                             f"current cap {cap_cur*100:.1f}%"
                             + (" (NOI est. from GSI)" if noi_estimated else ""))
    else:
        unassessed.append("cap (no NOI/GSI)")
    unassessed.append("cap_rate_stabilized + rent_upside (no rent_comps yet)")

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

    # DSCR
    dscr = None
    if noi and ask:
        loan = ask * A["ltv"]
        ads = mortgage_payment(loan, A["interest_rate"], A["amortization_years"]) * 12
        dscr = noi / ads if ads else None
        metrics["estimated_dscr"] = dscr
        components["dscr"] = (W["dscr"], dscr_score(dscr),
                              f"DSCR {dscr:.2f} @ {A['interest_rate']*100:.2f}% "
                              f"(floor {A['dscr_floor']})")
        flags["dscr_below_floor"] = dscr < A["dscr_floor"]
    else:
        unassessed.append("DSCR (no NOI)")

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

    # confidence: high needs real NOI + rent comps (impossible now); estimated NOI -> low
    if noi is None:
        confidence = "low"
    elif noi_estimated:
        confidence = "low"      # leans on estimated expense ratio
    else:
        confidence = "medium"   # real NOI figure but no rent comps -> not high

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
        "implied_cap_stabilized": None,
        "price_per_unit_vs_market": ppu_vs,
        "rent_upside_pct": None,
        "estimated_dscr": dscr,
        "estimated_irr_5yr": None,
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
