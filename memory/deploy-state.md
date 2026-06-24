---
name: deploy-state
description: Railway deploy prepared (config + guide); blocked on Railway auth — not yet live
metadata:
  type: project
---

Railway deployment PREPARED but NOT yet live as of 2026-06-22 — blocked on Railway auth (no
railway CLI installed, no RAILWAY_TOKEN; can't reach the control plane to create services / set
secrets / configure cron). The DB lives on Railway already (reseau.proxy.rlwy.net).

Artifacts in repo: `railway.json` (Nixpacks build, restartPolicy NEVER), `DEPLOY.md` (full recipe),
`scripts/daily_job.py` (single entrypoint: freshness sweep THEN briefing --send, for the daily cron),
complete `requirements.txt`. Plan = two cron services off GitHub repo benjamin-sylvester/RTP in the
SAME project as Postgres:
- rtp-ingest:   `python scripts/run_ingest.py`  cron `*/15 * * * *`  (also runs reply-to-kill)
- rtp-briefing: `python scripts/daily_job.py`   cron `30 10 * * *`  (= 6:30am EDT; UTC cron, DST drift)
Vars on both: DATABASE_URL, GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN, ANTHROPIC_API_KEY, CLAUDE_MODEL,
DISPATCH_EMAIL, GMAIL_DEAL_FLOW_LABEL, INGEST_AFTER_FLOOR.

TO FINISH: Ben does the Railway dashboard steps in DEPLOY.md (create 2 services from the repo, set
start command + cron + vars) OR installs railway CLI + gives a RAILWAY_TOKEN so the deploy can run
from here. Then confirm both jobs fire in Railway logs and the first rtp-ingest cycle picks up the
~3 unprocessed messages + any kill replies. NOTE: don't run run_ingest.py --commit locally before
deploy — it would consume/label the pending mail + kill replies meant for the first Railway run.

Also done this turn: AGED OUT briefing line tidied to descriptive labels (#id, units/address, city,
price). See [[briefing-state]].
