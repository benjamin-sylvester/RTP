# CLAUDE.md — RTP Deal Intelligence

Instructions for the Claude Code agent working in this repo.

## What this is
The deal intelligence system for Rising Tide Partners (RTP), a small balance multifamily
acquisitions platform in Southern NH. It turns broker emails and MLS exports into a
geocoded, auto-underwritten, queryable Postgres database. This database is the company's
core data asset.

## Architecture (read the gameplan)
The full design lives in `RTP_Deal_Intelligence_Gameplan_v2.md` (Section references below
point there). The short version: Postgres is the hub. This repo builds the server side
(ingestion, underwriting, API, dashboard). Cowork operates the business against the same
database via a Postgres MCP. Documents live in Google Drive and are linked from DB rows.

## Stack
- Postgres 16 on Railway (no PostGIS on the default image; schema uses lat/long + a haversine_miles() function for radius search)
- Python 3.12 for ingestion + underwriting (email, beautifulsoup, pymupdf, openpyxl, pandas)
- Claude API (model: claude-sonnet-4-6) for unstructured extraction and deal summaries
- FastAPI for the REST API
- React + Recharts + Mapbox GL for the dashboard
- APScheduler or Railway cron for the 15-minute ingestion job
- GitHub for version control, Railway auto-deploy from main

## Hard rules
- **Money is stored in cents** (BIGINT). Never use float for prices.
- **The buy box lives in `config/buy_box.yaml`** and nowhere else. Read it; never hardcode
  thresholds. Cowork reads the same file, so it is the single source of truth.
- **Broker column mappings live in `config/broker_format_config.yaml`** (and/or the
  `broker_format_config` table). Add a new broker by adding a config entry, not code.
- **Dedup before insert:** match on (a) external_id/MLS, then (b) fuzzy address+city, then
  (c) city + units + price/GSI within 5%, BUT only when one side lacks a usable address (this
  tier catches the SAME deal from a DIFFERENT sender/thread, e.g. an MLS blast and an addressless
  off-market email; two records with DISTINCT real addresses are never merged by (c) — tiers a/b
  govern those, to avoid collapsing two different properties that happen to share city/units/price).
  On match,
  **ENRICH** the existing row: fill null fields, prefer the more complete / higher-confidence
  value, and raise `listing_financials.confidence` accordingly. Never blind-overwrite good data
  and never create a duplicate row. Log every changed field to `listing_history`.
- **No orphan rows:** never persist a listing that has NEITHER a usable address NOR an
  external_id/MLS#. Dedup cannot protect such rows, so they silently breed duplicates.
  Quarantine them (a `needs_review` status / flag) for manual resolution instead of inserting.
- **Routing:** buy box fit or borderline -> status `lead`. Otherwise status `comp_only`.
  One table, never a second database.
- **Packages:** multi-parcel deals group under the `packages` table (migration 001) with
  member listings via `listings.package_id`. Evaluate buy box on `v_deals.effective_units`
  (combined unit count), NOT per parcel. Unit floor is 4, max 34 (see buy_box.yaml).
- **Every listing carries Drive pointers** when documents exist (`drive_folder_id`,
  `om_url`, `boe_url`).
- Keep secrets in `.env` (see `.env.example`). Never commit `.env`.

## Build order
Follow `BUILD_PLAN.md`. Do not jump ahead to the dashboard before ingestion works.
Test ingestion against real historical `Deal Flow` emails before wiring the cron.

## Data sources (the 5 known senders)
See `config/broker_format_config.yaml`. MLS exports (CSV/XLSX) parse with pandas via the
column map. Free-form broker emails and PDF OMs go through the Claude API parser.

## Validation
After any ingestion change, run the parser on a sample of historical emails and manually
verify extraction accuracy before trusting it. Calibrate the underwriting score against
10-15 deals Ben has already evaluated by hand.
