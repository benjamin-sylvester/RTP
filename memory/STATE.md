---
name: STATE
description: Current system state — what's live, what we just built, what's next, housekeeping
metadata:
  type: project
---

# RTP Deal Intelligence — STATE (read this first)

Snapshot as of late June 2026. Detailed history in the per-phase notes; this is the live picture.

## What's live (on Railway, auto-deploy from master)
- **Postgres** (the core data asset): ~72 listings + 2 packages, geocoded, auto-underwritten,
  HUD-FMR rent_comps. Migrations through 009 applied to the live DB.
- **Ingestion** (`rtp-ingest`, 15-min cron): Gmail "Deal Flow" -> parse (structured MLS + AI) ->
  dedup/enrich -> route (comp_only/lead) -> auto-underwrite. Also runs **reply-to-kill**.
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
