---
name: briefing-state
description: Daily briefing built; gmail.send added; test-send stage before scheduling 6:30am
metadata:
  type: project
---

Daily briefing built as of 2026-06-22 (BRIEFING_KICKOFF.md). Gmail OAuth re-consented to add
`gmail.send` (was `gmail.modify` only — can't send); both scopes now in the `.env` refresh token;
`gmail_client.send_html()` sends. Verified a scope test send to ben.sylvester18@gmail.com.

`ingest/briefing.py`: new leads (from `v_pipeline_deals`, ordered tier→confidence→score) +
listing_history changes (split PIPELINE vs MARKET-MOVES/comps so Fall River comp price cuts aren't
mistaken for pipeline) + needs_review, since a tracked `last_briefed_at`. HTML email led by TIER +
AI summary (score de-emphasized); price cuts flagged red; summary shortened to a 1-2 sentence lead
in the email via `short_summary()` (markdown stripped) while the FULL text stays in
`auto_underwriting.summary`. `last_briefed_at` lives in `system_meta` (migration 004) and advances
ONLY on a real send, so deals never repeat. Sends to `DISPATCH_EMAIL` (ben@rtprei.com).

`scripts/run_briefing.py`: `--dry` renders `briefing_preview.html` (no send, no timestamp); `--send
[--to X]` sends + advances timestamp. Dry-run reviewed: 13 leads, 2 market price cuts, 12 needs_review.

Test send to ben@rtprei.com done (msg 19ef67e1f323e602); last_briefed_at advanced. `run_briefing.py
--since YYYY-MM-DD` previews a wider window without touching the stored timestamp.

PIPELINE FRESHNESS (migration 005): `listings.last_seen_at` (backfilled from latest
listing_history.changed_at else date_ingested; DEFAULT NOW()). Ingestion refreshes it on insert AND
on every dedup-enrich match (re-seen deals stay active). `ingest/freshness.sweep()` demotes status
lead -> 'stale' where last_seen_at older than buy_box.yaml `pipeline.active_lead_days` (45); leaves
underwriting/under_contract; logs the status change. 'stale' stays in the DB as a comp (v_pipeline /
v_pipeline_deals already exclude it). `scripts/sweep.py` (--commit, or `--reactivate ID` to bring a
stale deal back to lead). The DAILY job order is: sweep THEN briefing. Sweep on current backfill
demoted 0 (all seen today); 13 leads still active. Demotion logic proven in rollback (60d lead->stale,
90d underwriting untouched).

NEXT (gated): Ben checks the inbox copy, THEN schedule the daily 6:30am job = sweep + briefing
(alongside the 15-min ingestion cron). NOT scheduled yet. See [[phase3-state]].
