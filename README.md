# rtp-deal-intel

Deal intelligence system for Rising Tide Partners. Turns broker emails and MLS exports into
a geocoded, auto-underwritten, queryable Postgres database. The database is the company's
core data asset; this repo is the server side that builds and feeds it.

## Read first
- `RTP_Deal_Intelligence_Gameplan_v2.md` — the full operating architecture (kept in the
  Drive `5.0 Organizational / 3.0 Deal Intelligence` folder).
- `CLAUDE.md` — rules for the Claude Code agent.
- `BUILD_PLAN.md` — sequenced build, phase by phase.

## Quick start
1. `cp .env.example .env` and fill in secrets.
2. Provision Railway Postgres + PostGIS.
3. `psql $DATABASE_URL -f db/schema.sql`
4. Connect the Postgres MCP to Cowork and Claude Code.
5. Follow `BUILD_PLAN.md` from Phase 0.

## Layout
```
db/schema.sql                     full DDL
config/buy_box.yaml               single source of truth for the buy box
config/broker_format_config.yaml  the 5 known deal-flow senders
PROMPTS.md                        prompt library (app + Cowork)
ingestion/                        Gmail -> parse -> geocode -> dedup -> insert  (to build)
underwriting/                     buy box + quick UW + scoring                  (to build)
api/                              FastAPI                                       (to build)
dashboard/                        React + Recharts + Mapbox                     (to build)
```

## Principles
- Postgres is the hub. Cowork and this app are spokes.
- One `listings` table is both the Sale Comp DB and the Pipeline (split by `status`).
- Buy box and broker mappings live in `config/`, never hardcoded.
- Money in cents. Dedup before insert. Documents in Drive, linked by URL from DB rows.
