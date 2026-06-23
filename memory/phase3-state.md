---
name: phase3-state
description: Phase 3 rent comps — HUD FMR baseline live; stabilized cap/upside/IRR un-stubbed; blended cap
metadata:
  type: project
---

Phase 3 (rent comps) underway as of 2026-06-22. THE rule: `market_rent` comes ONLY from market-asking
sources (`hud`/`zillow`/`costar`), NEVER in-place rent rolls — else the value-add upside is erased.
`ingest/underwrite.MARKET_SOURCES` enforces this. `rent_upside = market_median − in_place`.

DONE:
- `ingest/rentroll.py` — rent-roll PDF -> per-occupied-unit rent_comps (source `rent_roll`, in-place).
- `ingest/hud_fmr.py` — FY2025 HUD FMRs (token-free, curated) -> rent_comps (source `hud`), mapped to
  buy-box markets + Pittsfield/Allenstown. Town->area maps for Derry/Londonderry/Salem/Farmington/Milton
  flagged `approx_area_map` in raw_data. Refresh from HUD API once a HUD_API_TOKEN is added.
- `scripts/load_market_rents.py` — loads HUD + wires `unit_mix.market_rent` from MARKET sources only.
- Un-stubbed `underwrite.stabilized_block`: implied_cap_stabilized, rent_upside_pct, rough 5-yr IRR,
  from resolved unit mix (unit_mix table -> rent-roll comps -> raw_data unit_mix string) x market rents.

BLENDED CAP (Ben, Jun 22): scoring_weights split cap into cap_rate_stabilized 0.15 + cap_rate_current
0.10. Current cap MUST use normalized expenses (expense_ratio_default) or VERIFIED T-12 actuals —
NEVER the broker's headline NOI (the "Nashua trap"). `deal_financials` returns (gsi, verified_noi)
where verified_noi is set only from data_source='t12'; DSCR uses the same normalized NOI. Confidence:
high needs verified T-12 + market rents (no deal qualifies yet — no T-12 parsed); broker NOI never earns high.

Calibration after blended cap (YES 53 >> No 20, PASS): Amherst 15->42 (value-add upside +57% now
visible, ranks above all No), Nashua stays low at 20 (normalized current cap 5.2%, not broker's 7.6% —
confirmed no inflation), Pittsfield 58 (stab 7.4% + upside +48% from its rent roll).

NEXT: Zillow weekly scan (Claude in Chrome) for current asking rents -> rent_comps source `zillow`
(HELD until Ben connects the extension); parse the 9 Carroll T-12 xlsx for verified NOI (would lift
Pittsfield to high confidence). NOT the dashboard. See [[phase2-state]], [[BUILD_PLAN]].
