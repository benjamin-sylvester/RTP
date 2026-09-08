# RTP Deal Intelligence — Revival Runbook

Bringing the system back after the July 2026 outage (expired Gmail token +
lapsed Railway trial). Follow top to bottom in one sitting. ~30–45 min, mostly
waiting.

**Legend:** 🤖 = Claude runs it from the session · 🧑 = you do it (login,
browser, dashboard). Steps are ordered; don't skip ahead.

---

## Step 1 — Local environment  🤖

Claude installs Python 3.12, builds the venv, installs dependencies. If you're
running it yourself instead:

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
```

Python's PATH only updates in new shells, so if setup installs Python it will
stop and ask you to reopen the terminal and re-run. That's expected.

---

## Step 2 — Get your secrets back from Railway  🧑

`.env` is gitignored, so the fresh clone has none. Railway is the only place
these values still live.

1. Install the Railway CLI and log in (opens a browser):
   ```powershell
   npm i -g @railway/cli
   railway login
   ```
2. Link this folder to your project, then dump the ingest service's vars:
   ```powershell
   railway link
   railway variables --service RTP-INGEST --json > railway_vars.json
   ```
   `railway_vars.json` holds live secrets. It's now gitignored — leave it in
   this folder, don't email or paste it.

Then Claude rebuilds `.env` from it (🤖):

```powershell
.venv\Scripts\python.exe scripts\env_from_railway.py railway_vars.json
```

> If the DB host ends in `.railway.internal`, the script auto-swaps in the
> public URL so it works from your laptop. If it warns that no public URL was
> in the dump, open the Postgres service in Railway → Variables → copy
> `DATABASE_PUBLIC_URL`.

---

## Step 3 — Is the trial-paused Postgres still alive?  🧑

The Railway trial lapsed, which likely **paused** the project. Before anything
can connect, resume it:

- Railway dashboard → project `giving-sparkle` → if paused, **upgrade to Hobby
  ($5/mo)** and resume. This is the point where the monthly cost starts.

If the Postgres volume was reclaimed (only happens after long inactivity), the
data may be gone — that's what Step 4 checks. There is no local backup, so if
it's alive, **take a dump immediately** (Step 6).

---

## Step 4 — Diagnose  🤖

```powershell
.venv\Scripts\python.exe scripts\health_check.py
```

Read-only. Reports: how many listings are in the DB (the "worth it?" number),
whether dedup held, and — decisively — whether the Gmail token or the Anthropic
key is what died. Everything below assumes it confirms the expired Gmail token.

---

## Step 5 — Kill the 7-day token expiry, for good  🧑

The token expired because the OAuth consent screen is in **Testing** status,
which revokes refresh tokens after 7 days.

1. [Google Cloud Console](https://console.cloud.google.com) → the project with
   the Gmail API → **APIs & Services → OAuth consent screen**.
2. Click **PUBLISH APP** (Testing → In production). Confirm. Refresh tokens
   stop expiring. You'll later hit a one-time "Google hasn't verified this app"
   screen — click **Advanced → Go to (app)**. Fine for single-user; verification
   only matters past 100 users.

Then re-mint the token. Needs `client_secret.json` (the Desktop OAuth client
JSON) in the repo root:

```powershell
.venv\Scripts\python.exe scripts\gmail_auth.py
```

A browser opens — sign in as **ben.sylvester18@gmail.com** and consent. The new
`GMAIL_REFRESH_TOKEN` is written to `.env`.

---

## Step 6 — Back up the database  🧑

Now that it's reachable, snapshot it before touching anything. Straight into
Drive so it's backed up the instant it's written:

```powershell
railway run pg_dump "$env:DATABASE_URL" -Fc -f "G:/Shared drives/RTP G-Drive/6.0 Claude/rtp_railway_backup.dump"
```

This is the file that means a wiped machine or a lapsed trial can never cost you
the data again.

---

## Step 7 — Push the new token to Railway & redeploy  🧑

1. Railway → **both** `RTP-INGEST` and `RTP-BRIEFING` → Variables → update
   `GMAIL_REFRESH_TOKEN` to the new value now in `.env`.
2. Redeploy both. Watch `RTP-INGEST` logs for one clean cycle:
   ```powershell
   railway logs --service RTP-INGEST
   ```
   Success looks like `[ingest] done: {...}` with no `invalid_grant`.

---

## Step 8 — Rotate the exposed secrets  🧑

`memory/STATE.md` notes the live Postgres password was once printed to a log.
You're already in Railway, so rotate now:

- Postgres password (Railway → Postgres → regenerate; update `DATABASE_URL` on
  all services), `ANTHROPIC_API_KEY`, and the Gmail OAuth **client secret**.

---

## Done → then the second inbox

Once Step 7 shows a clean cycle, the system is live again. The work-inbox
(ben@rtprei.com) multi-account change is the clean follow-on — see the plan in
the session. It needs this running first so it's testable.
