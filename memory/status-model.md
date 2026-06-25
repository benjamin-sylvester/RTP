---
name: status-model
description: Deal status lifecycle (STATUS_MODEL.md) — statuses, sticky rule, activeness-by-date
metadata:
  type: project
---

Deal status set (migration 008, STATUS_MODEL.md): comp_only | lead | underwriting | loi_sent |
under_contract | lost | passed. Plus needs_review = system quarantine (no-orphan / unknown-units).
Retired: 'dead' (->passed) and 'stale' (->lead). lost = competed & didn't win; passed = chose not to
compete. Deferred: closed/owned (post-close).

STICKY RULE: ingestion auto-manages ONLY comp_only<->lead; underwriting/loi_sent/under_contract/
lost/passed are MANUAL and sticky. `dedup.enrich` refreshes data + last_seen_at on a re-sighting but
NEVER changes status. (A passed/lost deal isn't resurrected by a new MLS blast.)

ACTIVENESS IS BY DATE, NOT STATUS — the lead->stale sweep is GONE (scripts/sweep.py deleted,
freshness.sweep removed). Active = status in (lead,underwriting,loi_sent,under_contract) AND, for
LEADS only, last_seen_at within buy_box.yaml pipeline.active_lead_days (45). Manually-advanced deals
(underwriting+) are never time-filtered. Filtered in the app: api list (`quiet=true` shows quiet
leads) and the briefing (new_leads recency + "LEADS GONE QUIET (N)" by date, no status change).

`ingest/freshness.set_status(conn, kind, deal_id, new_status, reason)` does all transitions for
LISTINGS and PACKAGES, logs to listing_history (field 'status' for listings, 'package_status' on
member parcels), uses a tuple_row cursor (robust to the API's dict_row connection). kill() = ->passed;
reactivate() = ->lead. CLI: scripts/deal.py --status/--kill/--reactivate/--list. Reply-to-kill ->passed.

Dashboard slice 5: status buttons on the detail page (-> Underwriting / LOI sent / Under contract /
Lost / Passed / Reactivate), confirm on Lost/Passed, listings AND packages, via POST
/api/deals/{kind}/{id}/status (validates freshness.MANUAL_TARGETS). See [[briefing-state]].
