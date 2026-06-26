---
name: testing-against-live-db
description: Never run status/ingestion tests against the live DB — use throwaway DB or rolled-back txns
metadata:
  type: feedback
---

Do NOT run status-change or ingestion tests against the live Railway Postgres. They leave noise
(e.g. slice-5 dev left flip-flop status rows + dict_row-bug rows in listing_history that had to be
cleaned out, commit-era 2026-06-26).

**Why:** the live DB is the company's core data asset; test writes pollute the listing_history trail
and show up in the daily briefing ("changes" / status moves), making real activity hard to read.

**How to apply:** for any test that writes (set_status, dedup.upsert, kill/reactivate, backfills),
either (a) run inside a transaction and `conn.rollback()` at the end (the prove_nashua /
backfill_sample / sweep scripts already use this `--commit`-gated rollback pattern — copy it), or
(b) point at a throwaway/scratch database. Only persist to the live DB when the user explicitly asks
for a real change (a real backfill, a real status update). Read-only queries against live are fine.
See [[status-model]].
