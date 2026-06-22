# BUILD_PLAN.md — RTP Deal Intelligence

Sequenced build for the Claude Code agent. Do not skip ahead. Each phase ends with a
verification gate that must pass before moving on.

## Phase 0 — Foundation (gating step for everything)
1. Create a Railway project. Provision Postgres (default image has NO PostGIS; the schema uses
   lat/long + a haversine_miles() function instead, no spatial extension needed).
2. Run `db/schema.sql`. Confirm all tables, indexes, views, and the haversine_miles function exist.
3. Connect the **Postgres MCP** to both Cowork and Claude Code (read + write).
4. Load `config/broker_format_config.yaml` into the `broker_format_config` table.
5. Seed: import the existing Deal Database (22 deals, `RTP_Deal_Database.xlsx`) into
   `listings`. Map old columns to the new schema. Set status `comp_only` unless a deal is
   already in the pipeline.
**Gate:** a haversine_miles radius query and the `v_pipeline` view both return correct rows.

## Phase 1 — Ingestion + comp capture  (PRIORITY 1)
1. Gmail API auth (OAuth2 for the connected inbox). Query the `Deal Flow` label.
2. Attachment classifier: MLS export (CSV/XLSX) vs OM (PDF) vs rent roll vs T-12.
3. Structured path: pandas parse of MLS exports via `field_map`.
4. AI path: Claude API extraction for free-form emails and PDFs (see PROMPTS.md).
5. Geocode (Census first, Google fallback). Store PostGIS point.
6. Dedup (external_id -> fuzzy address -> price proximity). UPDATE + log on match.
7. Route on buy box: fit/borderline -> `lead`, else -> `comp_only`. Insert.
8. Backfill 3-6 months of historical `Deal Flow` emails to seed real data.
9. Wire the 15-minute cron.
**Gate:** run against 2 weeks of historical emails; manually verify extraction accuracy.

## Phase 2 — Auto-underwriting
1. Buy box filter from `config/buy_box.yaml` -> `auto_underwriting.buy_box_flags`.
2. Quick calcs: implied cap (current + stabilized), PPU vs submarket median, rent upside,
   estimated DSCR, rough 5-yr IRR. Assumptions from `buy_box.yaml`.
3. Composite score using `scoring_weights`.
4. Claude-generated 2-3 sentence summary.
**Gate:** scores on 10-15 hand-evaluated deals look sane. Calibrate weights.

## Phase 3 — Rent comps
1. Rent roll parser -> `rent_comps` (source `rent_roll`).
2. Weekly Zillow scan (Claude in Chrome) -> `rent_comps` (source `zillow`).
3. Wire `unit_mix.market_rent` to pull from `rent_comps` medians by market + unit type.
**Gate:** stabilized cap in auto-underwriting uses real market rents, not the default ratio.

## Phase 4 — API + dashboard
1. FastAPI: list deals, deal detail, radius search, market stats, comp pull.
2. React dashboard: deal table + filters, market charts, morning briefing view.
3. Mapbox map view (Phase 4b): markers by score/status, draw-radius comp search.
4. Deploy to Railway, auto-deploy from main.
**Gate:** morning briefing view shows last-48h deals sorted by score.

## Phase 5 — Asset management (defer)
Light AM only: lease-expiration tracking, monthly per-property variance. Build after
acquisitions are flowing.

---
Estimated build: 80-120 hours over 10-12 weeks at 2-4 hrs/day. The defensible payoff is a
live, self-updating, auto-underwritten deal database with geographic comp analysis that no
other small-balance operator in the region has.
