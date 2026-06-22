# Phase 0 Kickoff — stand up the database

This is the gating step. Until the Postgres database exists and the Postgres MCP is connected,
nothing structured can run. Here is exactly what to do, what I need from you, and the prompt to
hand Claude Code.

## Step 1 — what I need from you (accounts + credentials)
I cannot create accounts or hold your secrets. You set these up once, then paste the values into
`.env` (template already in the repo). About 30 minutes total.

1. **Railway account** (railway.app). Create a project, add **PostgreSQL**, and click
   **Claim Project** so it is not deleted. (No PostGIS needed; the schema uses lat/long +
   haversine.) From the Postgres service **Variables** tab, copy **`DATABASE_PUBLIC_URL`**
   (the public `*.proxy.rlwy.net` one, NOT the internal `*.railway.internal` `DATABASE_URL`).
2. **Anthropic API key** (console.anthropic.com) for the server-side parser. Copy the key.
3. **Gmail API access** for the ingestion job: in Google Cloud Console, enable the Gmail API,
   create an OAuth client, and generate a refresh token for the inbox that receives Deal Flow.
   (Separate from the Cowork Gmail connector, which is read-only.)
4. **Google Maps Geocoding key** (optional; Census geocoder is the free default).
   (No Slack. Briefings and alerts go out by email via the Gmail API creds in #3.)

Drop all of these into `.env` (copy from `.env.example`). Never commit `.env`.

## Step 2 — open Claude Code on this repo
Put the `rtp-deal-intel` folder under version control and open it in Claude Code:
```
cd rtp-deal-intel
git init && git add . && git commit -m "scaffold from gameplan v2"
```
Then create a GitHub repo and push (Claude Code can do this for you).

## Step 3 — the kickoff prompt (paste into Claude Code)

> Read CLAUDE.md, BUILD_PLAN.md, db/schema.sql, and the two config files. We are doing Phase 0
> only. Steps:
> 1. Connect to the Railway Postgres in DATABASE_URL (use the public proxy URL). Run
>    db/schema.sql. Note: PostGIS is NOT available on Railway's default image, so the schema
>    uses lat/long columns + a haversine_miles() function instead. Confirm all 7 tables, 2
>    views, the indexes, and the haversine_miles function exist.
> 2. Load config/broker_format_config.yaml into the broker_format_config table.
> 3. Seed the listings table from my existing Deal Database export (I will provide the xlsx).
>    Map old columns to the new schema. Set status to 'comp_only' unless a deal is clearly in
>    the active pipeline, in which case use 'lead' or 'underwriting'. Geocode each address and
>    populate the latitude/longitude columns.
> 4. Verify with two queries: a 10-mile radius search around Manchester NH using
>    haversine_miles(), and SELECT * FROM v_pipeline. Show me the results.
> Do not build ingestion, underwriting, the API, or the dashboard yet. Stop after Phase 0 and
> report what is in the database.

Provide it the seed file: `RTP_DealFlow_Triage_2026-06-22.xlsx` (this session) plus your older
`RTP_Deal_Database.xlsx` (22 deals) if you want both merged.

## Step 4 — connect the Postgres MCP (the bridge)
Once the database is live, add a **Postgres MCP connector** in BOTH Claude Code and Cowork,
pointed at the same `DATABASE_URL` (read + write). This is what lets me query and update the
database from Cowork. Tell me when it is connected and I will run a test query and set up the
morning-briefing and weekly Zillow scheduled tasks (both emailed to you).

## Then: Phase 1
With the database live and seeded, the next prompt to Claude Code is "build ingestion per
BUILD_PLAN.md Phase 1," followed by a backfill of 3 to 6 months of Deal Flow history. That turns
today's manual triage into the automated pipeline.
