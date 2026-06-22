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
def corridor_markets():
    bb = buy_box()
    out = set()
    for c in bb["geography"]["corridors"]:
        out.update(m.lower() for m in c["markets"])
    return out


def route(state, city, units, price_usd):
    """state, city: str; units: int|None; price_usd: number|None (effective values)."""
    bb = buy_box()
    reasons = []
    st = (state or "").strip().upper()
    if st != bb["geography"]["state"]:
        return "comp_only", [f"state {st or '?'} outside {bb['geography']['state']}"]

    umin, umax = bb["units"]["min"], bb["units"]["max"]
    units_ok = units is not None and umin <= units <= umax
    if not units_ok:
        reasons.append(f"units {units} outside {umin}-{umax}")

    pmin, pmax = bb["price"]["min_usd"], bb["price"]["max_usd"]
    price_ok = price_usd is None or (pmin <= price_usd <= pmax)
    if price_usd is not None and not price_ok:
        reasons.append(f"price ${price_usd:,.0f} outside ${pmin:,}-${pmax:,}")

    in_corridor = (city or "").strip().lower() in corridor_markets()

    if units_ok and price_ok and in_corridor:
        return "lead", ["fit: NH in-corridor, size+price ok"]
    if units_ok and price_ok and not in_corridor:
        return "lead", ["borderline: NH size+price ok, outside named corridors"]
    return "comp_only", reasons or ["does not meet buy box"]
