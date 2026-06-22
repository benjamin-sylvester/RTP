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

NEXT (not yet built): structured HTML parser for mlspin/primemls (parse:html, field_map); PDF/xlsx
attachment parsing; dedup + listing_history logging; package detection; routing via
`v_deals.effective_units`; then the GATE — 2-week backfill sample for Ben to verify, then the 15-min
cron. See [[phase0-state]] and [[BUILD_PLAN]].
