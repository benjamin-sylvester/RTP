# Dashboard Kickoff — v1 (table + detail + filters, single login)

A private web view of the deal database: browse, filter, drill into any deal, and manage status.
NOT public, NOT a rebuild of the briefing, this is where you go to explore the data asset on demand.

## Scope (v1 — confirmed)
- **In:** deal table with filters/sort, deal detail page, status actions (kill/reactivate/mark
  underwriting). Single password login.
- **Out (later, v2):** Mapbox map + radius search, trend/market charts. Don't build these yet.

## Architecture (keep it simple, one service)
- **One FastAPI service** that serves both a read API and the frontend (so it deploys as a single
  Railway web service). Reuse the existing DB connection and `routing.py`/config; do not duplicate.
- **Frontend:** a lightweight single-page app (React via CDN, or plain HTML + a little JS — your
  call, optimize for simplicity over tooling). No heavy build pipeline needed for v1.
- **Read-mostly:** all reads from the live Postgres. The only writes are the status actions below.
- **Connects to Postgres internally on Railway** (the same DATABASE_URL reference), so no network
  reachability issue.

## Auth (single user)
- One login gated by a `DASHBOARD_PASSWORD` env var. On success set a signed, HTTP-only session
  cookie. Railway serves over HTTPS, so a single password + cookie is sufficient for one user.
  No user table, no OAuth, don't over-build it.

## Views
**1. Deal table** (default = active pipeline: status lead/underwriting/under_contract)
- Columns: address (Maps link), city, units, asking, $/unit, tier, score, confidence, status,
  last_seen.
- Filters: tier, market/city, unit range, status, min score. Sort by any column (default tier ->
  confidence -> score, same as the briefing).
- Toggles to also show: comps (comp_only), stale, needs_review.

**2. Deal detail** (click a row)
- Header: address, units, ask, $/unit, tier, score + the component breakdown (each metric ->
  contribution), score_confidence, buy_box_flags.
- AI summary (full text, not the shortened briefing version).
- Financials + unit_mix (in-place vs market rent, rent_delta).
- Comps: nearby listings via `haversine_miles()` (e.g. same market or within X miles).
- listing_history: price/status changes over time (the motivated-seller trail).
- Links: Drive folder / OM / BOE (if present), source Gmail thread.

**3. Status actions** (the UI answer to "how do I kill deals")
- Buttons on the detail page (and ideally inline in the table): **Kill** (-> dead), **Reactivate**
  (-> lead), **Mark underwriting**. Reuse the existing `deal.py` lifecycle helpers. Log to
  listing_history. This makes the dashboard the easy way to prune, no CLI, no reply needed.

## Build in slices (checkpoint after each — don't do it all in one shot)
1. **API**: endpoints for list-deals (with filters), deal-detail, comps-for-deal. Test with curl,
   show me sample JSON.
2. **Auth**: single-password login + session cookie. Verify locked when logged out.
3. **Frontend table**: render the list with filters/sort against the API.
4. **Frontend detail**: the deal drill-down with summary, breakdown, comps, history, links.
5. **Status actions**: kill / reactivate / underwriting buttons, wired to the lifecycle helpers.
6. **Deploy**: a new Railway **web service** (always-on, NOT cron) from this repo, start command
   for the FastAPI app, env vars DATABASE_URL + DASHBOARD_PASSWORD. Confirm it loads over the
   Railway URL and login works.

## Notes
- This is an **always-on** service, unlike the two cron jobs, so it uses more Railway resources
  (watch the credit). A single small web service is fine within the ~$20/mo budget.
- Reuse, don't duplicate: same DB layer, same buy_box.yaml, same lifecycle helpers as the pipeline.
- You'll need to pick a `DASHBOARD_PASSWORD`.

## Paste-ready prompt
> Read DASHBOARD_KICKOFF.md. Build the v1 dashboard in slices, stopping after each for me to check.
> Start with slice 1 (the FastAPI read API: list-deals with filters, deal-detail, comps-for-deal),
> reusing the existing DB layer and config. Show me sample JSON from each endpoint before moving on.
> Do not build the map or charts. Do not deploy until slice 6.
