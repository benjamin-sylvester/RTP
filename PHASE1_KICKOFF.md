# Phase 1 Kickoff — ingestion + comp capture (the automated pipeline)

This turns the manual triage into the self-updating system: new Deal Flow emails get parsed,
geocoded, deduped, routed against the buy box, and written to the database every 15 minutes.

## What I need from you (credentials)
Add these to `.env` (Phase 0 only needed DATABASE_URL):

1. **`ANTHROPIC_API_KEY`** (console.anthropic.com) — for parsing free-form emails and PDF OMs.
2. **Gmail API OAuth** for the inbox that holds the Deal Flow label:
   `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`.
   Set this up for **ben.sylvester18@gmail.com** (that is where the forwarded deals land and
   where the `Deal Flow` label lives). Enable the Gmail API in Google Cloud Console, create an
   OAuth client (Desktop), and generate a refresh token.
3. `GMAIL_DEAL_FLOW_LABEL=Deal Flow` (already in .env.example).
4. `DISPATCH_EMAIL=ben@rtprei.com` — where the morning briefing gets sent.
5. `GOOGLE_MAPS_API_KEY` (optional; Census geocoder is the free default).

## Decisions already locked (Jun 22)
- Unit floor = **4** (was 5). In `buy_box.yaml`.
- Packages evaluated at **combined/portfolio unit count** via `v_deals.effective_units`.

## The kickoff prompt (paste into Claude Code)

> Read CLAUDE.md, BUILD_PLAN.md (Phase 1), buy_box.yaml, broker_format_config.yaml, and
> db/migrations/001_add_packages.sql. Build Phase 1 only.
>
> 0. Run migration db/migrations/001_add_packages.sql against the database (it is idempotent).
>    Then fix the known data issue: group 377/379/383 Manchester St into one package
>    ("377-383 Manchester St 9-unit package"), link the three parcels via package_id, and set
>    the package status to 'lead'. Confirm v_deals shows it as one 9-unit lead.
> 1. Gmail ingestion: authenticate with the GMAIL_* creds, query the "Deal Flow" label for
>    unprocessed threads. Pull bodies and attachments.
> 2. Classify each attachment: MLS export (CSV/XLSX) vs OM (PDF) vs rent roll vs T-12.
> 3. Structured path: parse MLS exports with pandas using broker_format_config field maps.
>    AI path: parse free-form emails and PDFs with the Claude API (prompts in PROMPTS.md),
>    returning the JSON schema there. Skip Candor meetup/event noise.
> 4. Geocode (Census first, Google fallback) -> latitude/longitude. Dedup: external_id ->
>    fuzzy address+city (fuzzystrmatch) -> address+units+price within 5%. On match, UPDATE and
>    log to listing_history.
> 5. Package detection: when an email/OM describes a multi-building package (e.g. "3 pack",
>    "portfolio", multiple addresses, "X-property"), create a packages row and link the parcels.
> 6. Route on buy box from buy_box.yaml, using v_deals.effective_units for unit count (floor 4,
>    max 34, Southern NH only): fit or borderline -> status 'lead', else 'comp_only'.
> 7. Backfill: run the parser over the last 3-6 months of Deal Flow history to seed real data.
> 8. Wire the 15-minute schedule (APScheduler or Railway cron) and label processed threads.
>
> Before the full backfill, run against ~2 weeks of historical emails and show me a sample of
> extracted listings so I can verify accuracy. Stop before auto-underwriting (Phase 2).

## Verification gate
- The Manchester St package shows as a single 9-unit lead in `v_deals`.
- A sample of 10-15 recently parsed listings matches the source emails on address, units, price.
- New Deal Flow emails appear in the database within ~15 minutes, correctly routed.

## After Phase 1
Phase 2 is auto-underwriting (buy-box flags, implied caps, DSCR, score, AI summary) reading
buy_box.yaml assumptions. Then I can set up the daily email briefing and weekly Zillow rent scan
from Cowork, and we test whether the Postgres MCP can reach Railway from here.
