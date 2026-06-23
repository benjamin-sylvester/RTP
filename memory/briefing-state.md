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

NEXT (gated): ONE test send to ben@rtprei.com, Ben checks the inbox copy, THEN schedule the daily
6:30am job (alongside the 15-min ingestion cron). NOTE: the test send advances last_briefed_at to
now, so it IS the first real briefing — later scheduled runs are incremental. See [[phase3-state]].
