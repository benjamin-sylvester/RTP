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
even though Ben is pursuing them as one 9-unit package. Phase 0 scripts live in `scripts/`; not
yet committed to git. Next is Phase 1 (ingestion) per [[BUILD_PLAN]]. See [[buy-box-source-of-truth]].
