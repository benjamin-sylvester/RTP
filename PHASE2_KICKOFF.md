# Phase 2 Kickoff — auto-underwriting

Turns raw listings into scored, prioritized deals. Every listing gets a quick screen written to
the `auto_underwriting` table, so `v_pipeline` surfaces deals ranked by score with an AI summary.
This is a fast screen to decide what's worth 30 minutes, NOT a replacement for the full BOE.

## What the score is and is NOT (read first)
The score is a **triage sort key, not a verdict**. It exists to answer "which new deals do I open
first," never "should I buy this." Hard requirements:
- **Never auto-reject a deal.** The screen ranks and flags; the human decides. Low score = lower
  in the queue, not discarded.
- **No black box.** Always store and surface the component breakdown (each metric + its
  contribution) and a list of what could NOT be assessed, so Ben sees why a deal scored what it
  did and what's missing.
- **Numbers can't see condition, deferred maintenance, real unit rents (pre-Phase-3),
  neighborhood block-by-block, parking, layout, or seller motivation.** The quick metrics
  capture only the quantitative shell. The qualitative judgment must ride in the AI summary
  (step 4), which reads the actual email/OM text.
- Consider presenting a coarse tier (e.g. Priority / Watch / Pass) alongside the 0-100 to avoid
  false precision. Calibration (step 5) decides how much weight the number earns.

## Before you start
- Set `assumptions.interest_rate` in `buy_box.yaml` to your actual current 30-yr quote (it's a
  placeholder at 7.0% right now). DSCR and debt sizing depend on it.
- `rent_comps` is still empty (Phase 3). So stabilized cap and rent-upside cannot be computed
  yet. The scorer must degrade gracefully: compute the components it can, renormalize the
  weights over what's available, and record which inputs were estimated vs real.

## Evaluate on v_deals (package-aware)
Run the buy-box test and metrics on `v_deals.effective_units` / `effective_ask`, so packages are
judged on combined size, not per parcel. Floor 4, max 34, Southern NH only (all from buy_box.yaml).

## The kickoff prompt (paste into Claude Code)

> Read CLAUDE.md, BUILD_PLAN.md (Phase 2), buy_box.yaml, and db/schema.sql (auto_underwriting).
> Build Phase 2 only: auto-underwriting. Write results to auto_underwriting (one row per deal).
>
> 1. Buy-box flags: evaluate each deal in v_deals against buy_box.yaml (units 4-34 on
>    effective_units, price range, year_built, geography, class if known). Write meets_buy_box
>    and a buy_box_flags JSONB of which criteria passed/failed and why.
> 2. Quick metrics (read all assumptions/rate from buy_box.yaml, never hardcode):
>    - implied_cap_current: noi/ask; if only GSI, apply expense_ratio_default to estimate NOI.
>    - price_per_unit_vs_market: this deal's PPU vs the median PPU of comps in the same
>      city/submarket already in the listings table (we have ~72). Flag >10% below median.
>    - estimated_dscr: 65% LTV, interest_rate, 30-yr amort; flag < dscr_floor.
>    - implied_cap_stabilized + rent_upside_pct: compute ONLY if rent_comps has data for the
>      market; else leave null and exclude from scoring (do not fabricate).
>    - estimated_irr_5yr: rough (reno_per_unit, raise to market over 18mo if rent data exists,
>      exit at stabilized cap minus exit_cap_compression_bps).
> 3. Composite score 0-100 using scoring_weights, renormalized over the components actually
>    available for that deal. Store the per-component breakdown (metric -> contribution) and the
>    list of components that could NOT be assessed in buy_box_flags, so the score is fully
>    explainable. Also derive a coarse tier (Priority / Watch / Pass). NEVER set a status that
>    discards a deal based on score alone. Also set a
>    score_confidence (high/medium/low) from data completeness: high = real NOI/T-12 + rent comps;
>    low = leans on a broker gross-rent claim, estimated expense ratio, or no rent comps. Surface
>    it beside the score so a thin-data score is never mistaken for a solid one.
> 4. AI summary: a 2-3 sentence Claude summary per deal that READS THE SOURCE email/OM text and
>    surfaces the qualitative signals the numbers miss: condition / deferred maintenance, seller
>    motivation ("owners retiring", price cuts), below-market rents, unit-mix quality, anything
>    notable. This is where deal judgment beyond PPU/cap lives. Direct, specific, no filler.
> 5. Run it over all current deals, then CALIBRATE: compare scores against the human buy-box
>    calls already in the data (the seeded triage YES/MAYBE/No and Deal Database "Buy Box Fit").
>    Show me a table of the 10-15 hand-evaluated deals: my human call vs the computed score, so I
>    can sanity-check before we trust it. Tune weights if the ranking looks off.
>
> Stop after calibration. Do not build the dashboard.

## Verification gate
- The deals you flagged YES by hand score visibly higher than the ones you passed on.
- No fabricated stabilized metrics where rent_comps is empty (those fields null, score renormalized).
- v_pipeline now shows score + summary for the 12 leads + package #1, ranked sensibly.

## After Phase 2
I wire the daily briefing email (top new/changed deals by score to ben@rtprei.com) and we start
Phase 3 (rent comps + weekly Zillow scan), which then unlocks the stabilized-cap and rent-upside
parts of the score that are stubbed out now.
