# Railway Deployment — RTP Deal Intelligence

Runs on Railway (not a local machine) in the **same project as the Postgres DB**: two cron
services + one always-on web dashboard, all off the GitHub repo (`benjamin-sylvester/RTP`).
Railway auto-deploys on push to `master`.

| Service | Start command | Schedule | What it does |
|---|---|---|---|
| `rtp-ingest` | `python scripts/run_ingest.py` | cron `*/15 * * * *` | every 15 min: pull Deal Flow, parse/dedup/route, **process reply-to-kill**, label processed |
| `rtp-briefing` | `python scripts/daily_job.py` | cron `30 10 * * *` | daily: send the briefing to `DISPATCH_EMAIL` (no sweep — activeness is by last_seen_at) |
| `rtp-dashboard` | `uvicorn api.main:app --host 0.0.0.0 --port $PORT` | **always-on web** | the private dashboard (table/detail/status actions); Railway gives it a public HTTPS URL |

> **Timezone:** Railway cron is **UTC**. `30 10 * * *` = 6:30am **EDT** (summer). In winter
> (EST) 6:30am ET is `30 11 * * *`. Adjust the briefing cron at the DST change, or set it once
> and accept the 1-hour seasonal drift.

## Steps (Railway dashboard — needs your login)
1. Open the existing project (the one with the Postgres service).
2. **+ New → GitHub Repo → `benjamin-sylvester/RTP`.** Name it **`rtp-ingest`**.
   - Settings → Deploy → **Custom Start Command**: `python scripts/run_ingest.py`
   - Settings → Deploy → **Cron Schedule**: `*/15 * * * *`
   - (`railway.json` already pins builder=NIXPACKS and restartPolicy=NEVER so a cron run exits cleanly.)
3. **+ New → GitHub Repo → same repo** again. Name it **`rtp-briefing`**.
   - Custom Start Command: `python scripts/daily_job.py`
   - Cron Schedule: `30 10 * * *`
4. **Variables** (set on BOTH services — or define as shared/project variables):
   - `DATABASE_URL` → reference the Postgres service: `${{Postgres.DATABASE_URL}}`
     (internal URL; the public proxy in `.env` also works)
   - `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN` — copy from `.env`
   - `ANTHROPIC_API_KEY`, `CLAUDE_MODEL=claude-sonnet-4-6`
   - `DISPATCH_EMAIL=ben@rtprei.com`
   - `GMAIL_DEAL_FLOW_LABEL=Deal Flow`, `INGEST_AFTER_FLOOR=2026/03/24`
5. Deploy. Watch **Deploy logs** of each service for the first scheduled run.

## rtp-dashboard (always-on web service — dashboard slice 6)
1. **+ New → GitHub Repo → same repo.** Name it **`rtp-dashboard`**.
   - Settings → Deploy → **Custom Start Command**: `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
     (Railway injects `$PORT`; do NOT set a cron schedule — this one stays running).
   - `railway.json` sets restartPolicy=NEVER, which is for the cron jobs — **override the dashboard
     service's restart policy to ON_FAILURE** (Settings → Deploy) so the web server restarts if it crashes.
   - Settings → Networking → **Generate Domain** to get the public HTTPS URL.
2. **Variables** (this service needs DB + auth only — no Gmail/Anthropic):
   - `DATABASE_URL` → `${{Postgres.DATABASE_URL}}`
   - `DASHBOARD_PASSWORD` → **pick a strong password** (this is the single login)
   - `DASHBOARD_SECRET_KEY` → a random 64-hex string (`python -c "import secrets;print(secrets.token_hex(32))"`); keep it stable so sessions survive restarts
   - `DASHBOARD_HTTPS=true` (Railway serves HTTPS, so the session cookie is secure-only)
3. Deploy, open the generated URL, confirm the login gate appears and the table loads after login.
4. **Cost note:** always-on uses more credit than the crons; one small web service fits the ~$20/mo budget.

## CLI alternative (non-interactive)
With the Railway CLI installed and a project token:
```
export RAILWAY_TOKEN=<project token from Railway → project → Settings → Tokens>
railway link            # select the project
railway up              # build/deploy current dir
railway variables --set GMAIL_REFRESH_TOKEN=... (etc.)
```
Cron schedule + start command per service are still set in the dashboard (Settings → Deploy).

## Verifying it runs ON RAILWAY (not locally)
- Each service's **Deployments → Logs** shows the cron firing. `run_ingest.py` prints
  `[ingest] N unprocessed message(s)` and `[reply-cmd] processed …`; `daily_job.py` prints
  `[daily] briefing: … SENT id=…`.
- Reply-to-kill is handled by `rtp-ingest` (it reads briefing replies each cycle), so it only
  works once that service is live on Railway.

## Notes
- One-time DB migrations (`db/migrations/00*.sql`) and the `last_seen_at` backfill were already
  applied to the live DB from here; the cron services only run the app, not migrations.
- Secrets live only in Railway variables + local `.env` (gitignored) — never in the repo.
