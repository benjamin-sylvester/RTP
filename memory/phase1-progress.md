---
name: phase1-progress
description: Phase 1 ingestion — Gmail live, AI parser validated; structured parser + dedup next
metadata:
  type: project
---

Phase 1 (ingestion) in progress as of 2026-06-22. Gmail OAuth is live for
ben.sylvester18@gmail.com (gmail.modify scope; refresh token in `.env`; `client_secret.json`
in repo root, gitignored). The "Deal Flow" label has 61 threads / 72 messages — all HTML-bodied.

Built so far: `ingest/gmail_client.py` (fetch/decode messages + attachments, `match_broker` with
exact-then-domain fallback), `ingest/parsers.py` (`html_to_text` + `ai_extract` via Claude
`claude-sonnet-4-6`, returns `{listings:[...]}`, filters newsletter noise). Helper scripts:
`gmail_auth.py`, `gmail_check.py`, `gmail_survey.py`, `test_parse.py`.

Corpus survey found 7 senders NOT in config; per Ben, added all to `broker_format_config.yaml`
(cbrealty, fallriverpm, bchomebuyers, htapartments + `self_forward` for Ben's own forwards) with
`domains:` fallback, and reloaded the table (10 sources). AI parser validated on real emails:
Porter Pittsfield (13u/$1.69M correct), Candor Nashua 6u (extracted $1.195M + unit mix + NOI),
Candor meetup -> 0 listings (noise filter works).

KEY DEDUP CASE: the Candor Nashua 6-unit (GSI $118,560) is the SAME deal as seeded triage lead #25
(Nashua addr TBD, same GSI) from a different sender/thread — the email reveals the price/unit mix the
triage lacked. Dedup (external_id -> fuzzy address+city -> units+price within 5%) must catch this and
ENRICH, not duplicate. Off-market addresses often live in attachment filenames (e.g. "9 Carroll St"),
not the body — need attachment/PDF parsing to resolve them.

BUILT since: `ingest/dedup.py` (3-tier match a:external_id, b:fuzzy address, c:city+units+price/GSI
within 5%. Tier b requires the HOUSE NUMBER to match then fuzzy-matches the street-name core
(suffix-normalized) so '383' vs '412 Manchester St' do NOT collapse but '74 Sutton St' vs '74 Sutton
Street' do. Tier c only fires when a side is addressless. Enrich fills nulls + logs every change to
listing_history, never overwrites/duplicates), `ingest/routing.py` (canonical buy_box reader),
`ingest/geocode.py`, `ingest/structured.py` (mlspin/primemls card parsers — NOT field_map exports;
they're formatted HTML cards), `ingest/attachments.py` (filename address hints + PyMuPDF text +
classify), `ingest/pipeline.py` (orchestrates). Scripts: prove_nashua.py, backfill_sample.py.

PROVEN: Nashua enrichment (#25 enriched from Candor email, COMMITTED). 2-week dry-run
(backfill_sample.py, after 2026/06/08): 5 msgs -> 7 listings, 6 new + 1 enriched; 575 Summer St
merged via MLS# across self_forward + primemls (no dup); routing correct. Sample ROLLS BACK by
default (--commit to persist). NOTE structured field_map in config is unused — real MLS emails are
HTML cards; parsed by regex in structured.py.

THREE FIXES applied + verified on clean 90-day dry-run (58 msgs -> 77 listings: 46 new, 30 enriched,
1 pkg-linked, 3 quarantined):
1. MLS-PIN addressless cards: regex now tolerates the search-area label, e.g. "26 Lee St, Worcester:
   WPI, MA" -> city Worcester. No more "?,?" orphan inserts.
2. No-orphan rule (CLAUDE.md): a candidate with no house-numbered address AND no MLS# is quarantined
   as status `needs_review` (dedup.is_orphan / insert_listing) instead of inserted as lead/comp.
   E.g. Candor city-only "?, Manchester" with no price/MLS -> needs_review. (Matches via tier-c still
   enrich.)
3. PDF vision: image/boilerplate PDFs that yield no text now render to PNGs (attachments.pdf_to_images)
   and go to Claude vision (parsers.ai_extract_images); pipeline tries text first, vision on empty
   result. Armory rider extracted (3 units, unit mix, GSI); two rider msgs dedupe on shared MLS#.
4. Package link: combined range listing "377-383 Manchester St" -> dedup.try_link_package sets
   package #1 asking_price ($1.725M) instead of wrongly enriching parcel #13. Parcels still enrich
   #13/#14/#15.

REAL BACKFILL COMMITTED (90 days, after 2026/03/24): DB now has 72 listings. v_pipeline = 12
standalone leads + package #1 ($1.725M). needs_review queue = 12 (9 in-box NH-corridor deals with
unknown units + 3 addressless orphans). 101-107 Putnam is a single lead (#322, appears once in
corpus). Price changes logged to listing_history: 33-35 Malvey $844.8k->$820k, 771 Rock $699.9k->
$649.9k.

Two more routing/enrich rules added: (1) routing.py — NH-corridor deal with UNKNOWN units + ok price
-> needs_review (don't let a missing 'Total Units' bury a lead); out-of-box unknown-units stay
comp_only. (2) dedup.enrich — asking_price CHANGE (newer differs from stored) updates current +
logs to listing_history (motivated-seller signal); backfill runs OLDEST-FIRST so newest price wins.

CRON WIRED: ingest/runner.py (run_once: process Deal Flow msgs lacking 'RTP/Ingested' label after
floor 2026/03/24, upsert, per-message commit+label; oldest-first; idempotent forward-only),
scripts/run_ingest.py (CLI: default=process, --dry, --label-baseline), scripts/scheduler.py
(APScheduler every INGEST_INTERVAL_MINUTES=15). Baseline-labeled the 58 backfilled msgs; run_once
now finds 0 unprocessed. TO RUN THE LOOP: start scripts/scheduler.py as a worker, or Railway cron
running run_ingest.py every 15 min. Known minor gaps: Armory vision returns owner LLC as address;
some primemls cards lack units (now safely -> needs_review). git push STILL pending (no remote).
Phase 1 effectively complete; next is Phase 2 (auto-underwriting). See [[phase0-state]], [[BUILD_PLAN]].
