---
name: STATE
description: Current system state — what's live, what we just built, what's next, housekeeping
metadata:
  type: project
---

# RTP Deal Intelligence — STATE (read this first)

Snapshot as of late June 2026. Detailed history in the per-phase notes; this is the live picture.

## What's live (on Railway, auto-deploy from master)
- **Postgres** (the core data asset): geocoded, auto-underwritten, HUD-FMR rent_comps.
  Migrations through 009 applied to the live DB.
- **Buy box is multi-state** (buy_box.yaml v2026-06-29): NH (home turf — in-state deals are
  leads even outside a named corridor) + **MA SouthCoast corridor** (Fall River, New Bedford).
  All-of-MA is NOT in box — only the SouthCoast cities. Routing matches city+state.
- **Ingestion** (`rtp-ingest`, 15-min cron): Gmail "Deal Flow" -> parse (structured MLS + AI) ->
  dedup/enrich -> route (comp_only/lead) -> auto-underwrite. Also runs **reply-to-kill** and
  **engagement auto-promotion** (see below).
- **Daily briefing** (`rtp-briefing`, 6:30am ET): HTML email to ben@rtprei.com — new leads,
  changes, "leads gone quiet", needs_review.
- **Dashboard** (`rtp-dashboard`, always-on web, single-password): deal table + filters/toggles,
  detail page (score breakdown, financials, unit mix, comps, history, links), status actions.
- Confirmed in active use: the cron ingested `806 Union St` on 2026-06-28, and deals have been
  promoted/exited via the dashboard (Amherst -> lost, 377-383 package -> passed) — i.e. the
  deployment is live and Ben is operating it.

## What we just built — engagement & promotion
- **Deal status lifecycle** (STATUS_MODEL.md, migration 008): system auto-moves only
  comp_only<->lead; manual **promotion** through underwriting -> loi_sent -> under_contract, with
  lost/passed exits. Manual statuses are sticky (ingestion never overrides them). Activeness is by
  `last_seen_at` within active_lead_days (45) — no 'stale' status; quiet leads flagged by date.
- **Dashboard status actions** (slice 5): buttons to promote/exit a deal (Underwriting / LOI sent /
  Under contract / Lost / Passed / Reactivate), confirm on Lost/Passed, listings AND packages,
  logged to listing_history.
- **Source / Broker surfacing** (migration 009): table column + detail "Contact" line — MLS deals
  show "MLS"; broker deals show the broker name as a `mailto:` link for one-click outreach.
- **Engagement auto-promotion** (`ingest/engagement.py`, every cycle): if Ben REPLIED in a deal's
  Gmail thread, the deal is a pipeline deal regardless of buy box. Finds threads Ben SENT mail in
  (one `in:sent` list call), matches by raw_email_id, AI-infers stage from his own words
  (tour / P&L / rent-roll -> underwriting; offer / LOI -> loi_sent; else lead; a *decline* like
  "too rural" promotes nothing). Forward-only (never downgrades), sticky terminals
  (passed/lost/under_contract) are flagged not flipped, package members skipped, logged to
  listing_history. Wired into `runner.run_once` right after reply-to-kill (commit-only).
- **MA SouthCoast launch (2026-06-29)**: `scripts/ma_southcoast.py` created the Sprague+Nelson
  package (#4: 282 Sprague St Fall River + 49 Nelson St New Bedford, 12u $1.62M, Lyndsey Pachon,
  -> underwriting) and re-routed MA comps — 14 Fall River/New Bedford deals promoted comp_only->lead.

## What's next
- **UI / buttons polish** — dashboard refinements (inline status actions in the table, tighter
  layout, confirm/undo affordances). Map + market charts are still deferred to v2.
- **BOE generator** — back-of-envelope model beyond the quick triage score: pull market rents by
  unit type, run the annual DCF, write the BOE to Drive, set the deal to underwriting with boe_url
  (see PROMPTS.md "Build a BOE" + the gameplan). The deeper underwriting layer the score gates into.

## Open housekeeping
- **Key rotation** — rotate `.env` secrets periodically: DATABASE_URL password, GMAIL_* OAuth,
  ANTHROPIC_API_KEY. NOTE: the live Postgres password was printed once to a terminal/log earlier in
  development — rotate it in Railway and update `.env` + Railway vars.
- **Inbox filter** — Gmail filter so every deal-flow sender auto-applies the "Deal Flow" label
  (the corpus survey found senders that weren't captured); keeps ingestion complete and filters
  meetup/newsletter noise at the inbox.

See [[status-model]], [[deploy-state]], [[phase3-state]], [[testing-against-live-db]].
