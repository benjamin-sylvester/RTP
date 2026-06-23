---
name: phase2-state
description: Phase 2 auto-underwriting built + calibrated; rank by tier→confidence→score
metadata:
  type: project
---

Phase 2 (auto-underwriting) done as of 2026-06-22, calibrated and verified by Ben. The score is a
TRIAGE SORT, never a verdict — never auto-rejects. `ingest/underwrite.py` computes buy-box flags +
quick metrics on `v_deals` (package-aware) and writes `auto_underwriting`. Migration 002 added
`score_confidence`, `tier`, and `package_id` (a row targets a listing XOR a package) plus view
`v_pipeline_deals` (package-aware pipeline).

All assumptions/weights/rate read from `buy_box.yaml` (interest_rate 0.0625). rent_comps empty
(Phase 3) so stabilized cap / rent_upside / IRR are left NULL and excluded; weights renormalize over
available components (cap-current, PPU-vs-market, DSCR, unit sweet-spot, DOM). Every au row stores an
explainable `buy_box_flags._score_breakdown` (weight→contribution→detail), `_not_assessed`, and
`_component_score` (pre-gate). Out-of-box deals get score ×0.3 (`OUT_OF_BOX_SCORE_FACTOR`) so comps
sink below leads — never discarded. Tier cutoffs live in buy_box.yaml `tiers` (priority_min 65,
watch_min 40), read by the scorer — never hardcoded. score_confidence: medium if a
real NOI figure exists, low if estimated-from-GSI / broker-claim / no financials (never high until
rent comps). `ingest/summarize.py` AI summary READS source email/OM text (Gmail thread_text, HTML
fallback) for qualitative signals.

Calibration (scripts/calibration.py) vs Ben's hand calls: YES mean 58 >> No mean 20 (PASS). Known
divergences Ben accepted: 9 Carroll Pittsfield scores 100 but confidence low + summary says thin
("cold pitch") — number can over-rank thin data; 339 Amherst (YES) scores 15 — quant can't see
below-market rents until Phase 3. So pipeline RANK = tier, then score_confidence, then score (a
low-confidence high score must not top the list) — see v_pipeline_deals (migration 003).

NEXT: Phase 3 (rent comps) per [[BUILD_PLAN]] — rent-roll parser -> rent_comps; weekly Zillow scan
(Claude in Chrome); wire unit_mix.market_rent from rent_comps medians; THEN stabilized cap +
rent_upside + IRR come off the stubs. NOT the dashboard yet. See [[phase1-progress]].
