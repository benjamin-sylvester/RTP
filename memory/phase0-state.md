---
name: phase0-state
description: Phase 0 foundation is complete — DB schema applied and seeded on Railway
metadata:
  type: project
---

Phase 0 (foundation) is done as of 2026-06-22. The Railway Postgres in `.env` `DATABASE_URL`
has the full `db/schema.sql` applied (7 tables, 2 views, 8 indexes, `haversine_miles()`),
`broker_format_config` loaded from the YAML (5 senders), and `listings` seeded with 22 deals
(5 `lead`, 17 `comp_only`) all geocoded.

Seed came from `RTP_Deal_Database.xlsx` ONLY — the `RTP_DealFlow_Triage_2026-06-22.xlsx` file
Ben referenced did not exist on disk. If that Triage export appears, re-run `scripts/seed_listings.py`
(it truncates + reseeds idempotently).

Conventions established: `asking_price` AND `price_per_unit` are stored in CENTS (divide by 100
for display). NH "Unknown"-street deals (Candor Manchester batch, Pittsfield, Allenstown) use a
city-centroid geocode fallback, so they cluster on the same lat/long — refine before any map view.
Routing nuance: 377/379/383 Manchester St are 3 separate 3-unit `comp_only` rows (fail 5-unit min)
even though Ben is pursuing them as one 9-unit package. Phase 0 scripts live in `scripts/`
(committed in fd6066b).

Migration `001_add_packages.sql` IS applied (packages table, `listings.package_id`, `v_deals`).
Two packages grouped from existing parcels via `scripts/apply_packages.py`: #1 377-383 Manchester St
(3 parcels, 9 units, lead, ask incomplete — only 377 priced $499k) and #2 Providence portfolio
(4 parcels, 12 units, comp_only, RI/out-of-box). Member parcels keep their own status but drop out
of the standalone `v_deals` list and roll up on combined units.

From `RTP_DealFlow_Triage_2026-06-22.xlsx` (9-row "Deal Flow Log"), Ben had me seed only 3 NH deals
as leads via `scripts/seed_triage.py` (ids 23-25), each with `raw_email_id` = its Gmail thread id so
Phase 1 dedups on thread: 339-341 Amherst St Manchester (6u $1.35M, 19edc469c20448dd), 805 Central Ave
Dover (4u $800k, 19edc4628cc30d16 — the deal the 5->4 floor unlocks), Nashua 6-unit addr TBD (no price,
19e7064253032ca2). Deliberately NOT seeded: dataless rows (Cushing, 14-unit unknown loc) and PDF-rider
packages (1&3 Armory Rd) — Phase 1 ingests those from source. Hampton Beach 46u and Fall River 3-pack
left as comp_only watch, no action. Listings now total 25; 8 standalone leads in v_pipeline.

Next is Phase 1 (ingestion) per [[BUILD_PLAN]]. NOTE: git push still pending — repo has no remote and
`gh` is not installed; needs a GitHub remote URL before any push.
