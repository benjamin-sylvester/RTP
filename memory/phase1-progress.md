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

NEXT (after Ben verifies sample): widen backfill if needed (gate wants 10-15 listings; 2wk only had
7), then --commit the real backfill, then wire 15-min cron (APScheduler/Railway) + 'RTP/Ingested'
label on processed threads. Pipeline code is committed through e96074d ONLY — dedup/structured/
attachments/pipeline still UNCOMMITTED. Also: CLAUDE.md dedup-rule edit + git push still pending
(no remote). See [[phase0-state]] and [[BUILD_PLAN]].
