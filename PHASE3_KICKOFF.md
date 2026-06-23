# Phase 3 Kickoff — rent comps (unlocks stabilized cap + rent upside)

Goal: make `implied_cap_stabilized`, `rent_upside_pct`, and the 5-yr IRR computable so the
auto-underwriting score finally reflects RTP's value-add thesis (today they're stubbed null and
weighted out, which is why Amherst, a real value-add YES, scored 15).

## THE critical distinction (get this right or the whole phase is wrong)
There are TWO kinds of rent, and they must never be averaged together:

- **In-place rent** = what current tenants pay (from RENT ROLLS, source `rent_roll`). For a
  value-add deal these are deliberately BELOW market. This is the starting point of the gap.
  Feeds `unit_mix.avg_rent`, tied to the specific listing.
- **Market rent** = what a unit would rent for today if vacant (from MARKET-ASKING sources:
  Zillow, CoStar, HUD FMR; source `zillow`/`costar`/`hud`). This is the target.

`market_rent` for the stabilized calc must come ONLY from market-asking sources. If you let
below-market in-place rent rolls flow into `market_rent`, you erase the very upside you're trying
to measure, the system would conclude there's no value-add precisely on the deals that have the
most. Rent rolls inform in-place; market sources inform market. `rent_upside = market_median - in_place`.

## Sources of market breadth (in priority order)
1. **HUD Fair Market Rents** (recommended first — free, no scraping, reliable). Published by
   county + bedroom count, via the HUD USER API. Gives an immediate market-rent baseline for
   every NH market in the buy box with zero dependencies. source `hud`. Build this first so the
   stabilized calc has real data even before Zillow.
2. **Zillow weekly scan** (Claude in Chrome) for current asking rents by market + unit type.
   Richer and more current than HUD, but needs the Chrome extension connected and is fragile
   (Zillow blocks scraping), so treat it as enrichment on top of the HUD baseline, not the sole
   source. Markets to scan come from `buy_box.yaml` geography. source `zillow`.
3. **Broker rent rolls** as they arrive (already built) — in-place data, source `rent_roll`.

## Build steps
1. HUD FMR loader -> `rent_comps` (source `hud`) for all buy_box markets, by bedroom/unit_type.
2. Wire `unit_mix.market_rent` = median of MARKET-source comps (`hud`/`zillow`/`costar`, NOT
   `rent_roll`) for that market + unit_type. Recompute `rent_delta_pct`.
3. Un-stub the underwriter: `implied_cap_stabilized` (market rents + stabilized_occupancy +
   expense ratio), `rent_upside_pct` (market vs in-place), and the 5-yr IRR. Add these back into
   the renormalized score weights.
4. Re-run the scorer and the calibration table.
5. Zillow scan + weekly schedule (after Chrome is connected).

## Verification gate
- `market_rent` is sourced only from market-asking comps, never from in-place rent rolls.
- Stabilized cap + rent upside are non-null for markets that have comps.
- Re-run calibration: value-add deals with below-market in-place rents (Amherst, Nashua) should
  now RANK UP, because the upside is finally visible. That rank shift is the proof Phase 3 worked.

## Dependency
The Zillow scan needs the Claude-in-Chrome extension connected. The HUD FMR baseline does not, so
if Chrome isn't ready, build HUD first and add Zillow later. Either way the stabilized calc gets
real market rent.
