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
stale deal back to lead). The DAILY job order is: sweep THEN briefing.

CAVEAT FIXED: migration 005's backfill set last_seen_at to today (ingest/history all happened during
the backfill), so nothing aged out. `scripts/backfill_last_seen.py` corrects it to each deal's TRUE
source date = most recent Gmail internalDate across its raw_email_id thread AND any digest carrying
its external_id/MLS#, then listing_date, then date_ingested (70 gmail / 2 listing_date). After that,
sweep (active_lead_days 45, cutoff ~May 8) demoted 5 leads -> stale (4 Candor Manchester last seen
2026-03-24, 9 Carroll Pittsfield 2026-04-02); 7 listing-leads + package = 8 active.

PACKAGE FRESHNESS (migration 006): `packages.last_seen_at` = max(member last_seen_at); the sweep
recomputes it and demotes stale 'lead' packages too. Package #1 (377-383 Manchester) last_seen
2026-04-03 would have aged out, but Ben set it to status 'underwriting' (actively pursued, RR+P&L
received April) -> exempt, stays in pipeline. Briefing now splits lead->stale demotions into their
own "AGED OUT (N)" line (not under MARKET MOVES, which is comps only).

BRIEFING UX (Jun 22): each deal shows its id; addresses link to Google Maps; AI summaries are now
<=3 ultra-terse bullets (ingest/summarize.py), BLANK when nothing notable (bare-MLS deals empty).
Manual prune: `scripts/deal.py --kill ID [reason]` (-> 'dead'), `--reactivate ID`, `--list`
(freshness.kill/reactivate). REPLY-TO-KILL: reply to a briefing with "kill 24, 25" -> ingestion job
(runner.run_once calls ingest/reply_commands.process_replies) parses ONLY the typed reply (above the
quoted original, so quoted/example ids are ignored), sets those listings dead, labels the reply
RTP/CmdProcessed so it runs once. Briefing has a footer explaining it. Corrected copy re-sent to
ben@rtprei.com (msg 19ef6c156bed9b2d). Still NOT scheduled.

NEXT (gated): Ben checks the inbox copy, THEN schedule the daily 6:30am job = sweep + briefing
(alongside the 15-min ingestion cron). NOT scheduled yet. See [[phase3-state]].
