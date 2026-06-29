"""Buy-box routing — the single code path that reads config/buy_box.yaml.
Evaluates a deal (using effective/combined unit count for packages) and returns
('lead'|'comp_only', reasons[]). Fit or borderline -> lead, else comp_only."""
import functools
import pathlib
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent


@functools.lru_cache(maxsize=1)
def buy_box():
    return yaml.safe_load((ROOT / "config" / "buy_box.yaml").read_text())


@functools.lru_cache(maxsize=1)
def allowed_states():
    """States we'll consider at all. Supports the new `states` list and the legacy
    single `state` scalar."""
    geo = buy_box()["geography"]
    if geo.get("states"):
        return {s.strip().upper() for s in geo["states"]}
    return {geo["state"].strip().upper()}


@functools.lru_cache(maxsize=1)
def primary_state():
    """Home-turf state: in-state deals are (borderline) leads even outside a named
    corridor. Other allowed states are in-box ONLY via a named corridor."""
    geo = buy_box()["geography"]
    return (geo.get("primary_state") or geo.get("state") or "").strip().upper()


@functools.lru_cache(maxsize=1)
def corridor_pairs():
    """Set of (STATE, city-lower) the named corridors cover. State-aware so a MA SouthCoast
    city is only in-box in MA, never matched by a same-named city in another state. A corridor
    without an explicit `state` falls back to the legacy single geography state."""
    bb = buy_box()
    default_st = (bb["geography"].get("state") or "").strip().upper()
    out = set()
    for c in bb["geography"]["corridors"]:
        st = (c.get("state") or default_st).strip().upper()
        out.update((st, m.lower()) for m in c["markets"])
    return out


def route(state, city, units, price_usd):
    """state, city: str; units: int|None; price_usd: number|None (effective values).
    Returns ('lead'|'comp_only'|'needs_review', reasons[])."""
    bb = buy_box()
    st = (state or "").strip().upper()
    in_corridor = (st, (city or "").strip().lower()) in corridor_pairs()
    in_primary = st == primary_state()
    pmin, pmax = bb["price"]["min_usd"], bb["price"]["max_usd"]
    price_ok = price_usd is None or (pmin <= price_usd <= pmax)
    umin, umax = bb["units"]["min"], bb["units"]["max"]

    if st not in allowed_states():
        return "comp_only", [f"state {st or '?'} outside {sorted(allowed_states())}"]

    # Lead-eligible geography = a named corridor (any allowed state) OR the primary state.
    # Non-primary allowed states (e.g. MA) are in-box ONLY via a corridor.
    lead_geo = in_corridor or in_primary

    # Unknown units: a missing 'Total Units' must not bury a real lead. Lead-eligible
    # geography + acceptable price -> needs_review for a human to confirm size.
    # Out-of-box (geography or price) -> comp_only.
    if units is None:
        if lead_geo and price_ok:
            return "needs_review", ["in-box geography but unit count unknown -> review"]
        why = ["units unknown"]
        if not lead_geo:
            why.append("outside corridors / primary state")
        if not price_ok:
            why.append(f"price ${price_usd:,.0f} out of range")
        return "comp_only", why

    units_ok = umin <= units <= umax
    reasons = []
    if not units_ok:
        reasons.append(f"units {units} outside {umin}-{umax}")
    if price_usd is not None and not price_ok:
        reasons.append(f"price ${price_usd:,.0f} outside ${pmin:,}-${pmax:,}")

    if units_ok and price_ok and in_corridor:
        return "lead", [f"fit: {st} in-corridor, size+price ok"]
    if units_ok and price_ok and in_primary:
        return "lead", [f"borderline: {st} size+price ok, outside named corridors"]
    return "comp_only", reasons or ["does not meet buy box"]
