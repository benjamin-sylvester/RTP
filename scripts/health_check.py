"""Read-only system health check for the RTP deal intelligence stack.

Answers two questions after the June/July outage:
  1. Is the credential that broke ingestion actually the Gmail refresh token?
  2. How much real data is in the live Postgres -- i.e. is it worth paying to keep?

STRICTLY READ-ONLY. Runs SELECTs, lists Gmail labels, lists Anthropic models.
It never writes to the database, never labels or sends mail, and never runs
ingestion. Safe to run against production.

    .venv\\Scripts\\python.exe scripts\\health_check.py
"""
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

GREEN, RED, YELLOW, DIM, RESET = "\033[92m", "\033[91m", "\033[93m", "\033[2m", "\033[0m"
if os.name == "nt":
    os.system("")  # enable ANSI on Windows terminals

findings = []   # (level, message) -- collected for the summary


def hdr(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def ok(msg):
    print(f"  {GREEN}OK{RESET}   {msg}")


def bad(msg):
    print(f"  {RED}FAIL{RESET} {msg}")
    findings.append(("fail", msg))


def warn(msg):
    print(f"  {YELLOW}WARN{RESET} {msg}")
    findings.append(("warn", msg))


def info(msg):
    print(f"       {DIM}{msg}{RESET}")


def usd(cents):
    return f"${cents / 100:,.0f}" if cents is not None else "-"


# =====================================================================
# 1. Environment
# =====================================================================
def check_env():
    hdr("1. ENVIRONMENT")

    env = ROOT / ".env"
    if not env.exists():
        bad(".env not found -- nothing can connect")
        info("railway variables --json > railway_vars.json")
        info("python scripts/env_from_railway.py railway_vars.json")
        return False

    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

    ok(".env loaded")
    required = ["DATABASE_URL", "ANTHROPIC_API_KEY", "GMAIL_CLIENT_ID",
                "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"]
    complete = True
    for k in required:
        v = os.environ.get(k, "")
        if v:
            ok(f"{k:<22} set  ({len(v)} chars, ...{v[-6:]})")
        else:
            bad(f"{k:<22} MISSING")
            complete = False
    return complete


# =====================================================================
# 2. Database
# =====================================================================
def check_db():
    hdr("2. DATABASE")
    try:
        from _conn import connect
    except Exception as e:
        bad(f"cannot import scripts/_conn.py: {e}")
        return None

    try:
        conn = connect()
    except Exception as e:
        bad(f"connection failed: {type(e).__name__}: {e}")
        info("If this is a timeout, the Railway Postgres may already be paused.")
        return None

    ver = conn.execute("SELECT version()").fetchone()[0]
    ok(f"connected -- {ver.split(',')[0]}")

    size = conn.execute(
        "SELECT pg_size_pretty(pg_database_size(current_database()))").fetchone()[0]
    ok(f"database size: {size}")
    return conn


def check_schema(conn):
    hdr("3. SCHEMA")
    tables = {r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_type='BASE TABLE'").fetchall()}
    views = {r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.views "
        "WHERE table_schema='public'").fetchall()}

    expected_tables = ["listings", "listing_financials", "unit_mix", "auto_underwriting",
                       "rent_comps", "listing_history", "broker_format_config",
                       "packages", "system_meta"]
    expected_views = ["v_pipeline", "v_sale_comps", "v_deals",
                      "v_pipeline_deals", "v_deal_board"]

    for t in expected_tables:
        ok(f"table {t}") if t in tables else bad(f"table {t} MISSING")
    for v in expected_views:
        ok(f"view  {v}") if v in views else warn(f"view  {v} missing")

    # migrations 005/009 add these; their presence proves how far the live DB got
    cols = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='listings'").fetchall()}
    for c in ("package_id", "last_seen_at"):
        ok(f"listings.{c} present") if c in cols else warn(f"listings.{c} missing")

    return tables, views


# =====================================================================
# 4. Data inventory -- the "is it worth paying for" numbers
# =====================================================================
def check_data(conn, tables):
    hdr("4. DATA INVENTORY")

    counts = {}
    for t in sorted(tables):
        try:
            counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except Exception:
            counts[t] = None
    for t, n in counts.items():
        print(f"       {t:<26} {n if n is not None else '?':>8}")

    n_listings = counts.get("listings") or 0
    if n_listings == 0:
        bad("listings is EMPTY -- there is no data asset here to preserve")
        return counts
    ok(f"{n_listings} listings")

    print(f"\n  {DIM}-- by status --{RESET}")
    for status, n, val in conn.execute(
            "SELECT status, COUNT(*), SUM(asking_price) FROM listings "
            "GROUP BY status ORDER BY COUNT(*) DESC").fetchall():
        print(f"       {status:<18} {n:>5}   {usd(val):>14}")

    print(f"\n  {DIM}-- ingestion timeline --{RESET}")
    row = conn.execute(
        "SELECT MIN(date_ingested)::date, MAX(date_ingested)::date, "
        "       COUNT(*) FILTER (WHERE date_ingested > NOW() - INTERVAL '30 days') "
        "FROM listings").fetchone()
    info(f"first ingested : {row[0]}")
    info(f"last  ingested : {row[1]}")
    info(f"last 30 days   : {row[2]} listings")

    if row[1]:
        gap = conn.execute(
            "SELECT (CURRENT_DATE - MAX(date_ingested)::date) FROM listings").fetchone()[0]
        if gap and gap > 7:
            warn(f"nothing ingested in {gap} days -- consistent with the cron being dead")

    print(f"\n  {DIM}-- source mix --{RESET}")
    for src, n in conn.execute(
            "SELECT source, COUNT(*) FROM listings GROUP BY source "
            "ORDER BY COUNT(*) DESC").fetchall():
        print(f"       {src:<18} {n:>5}")

    return counts


# =====================================================================
# 5. Data quality -- does dedup actually hold?
# =====================================================================
def check_quality(conn, counts):
    hdr("5. DATA QUALITY")

    n = counts.get("listings") or 0
    if not n:
        return

    dupes = conn.execute(
        "SELECT LOWER(TRIM(address)), city, state, COUNT(*) AS c "
        "FROM listings WHERE address IS NOT NULL AND TRIM(address) <> '' "
        "GROUP BY 1,2,3 HAVING COUNT(*) > 1 ORDER BY c DESC LIMIT 15").fetchall()
    if dupes:
        warn(f"{len(dupes)} exact duplicate address groups")
        for a, c, s, cnt in dupes:
            info(f"{cnt}x  {a}, {c} {s}")
    else:
        ok("no exact duplicate addresses -- dedup is holding")

    orphans = conn.execute(
        "SELECT COUNT(*) FROM listings "
        "WHERE (address IS NULL OR TRIM(address) = '') AND external_id IS NULL"
    ).fetchone()[0]
    if orphans:
        warn(f"{orphans} orphan rows (no address, no external_id) -- should be quarantined")
    else:
        ok("no orphan rows -- the no-orphan rule is holding")

    geo = conn.execute(
        "SELECT COUNT(*) FILTER (WHERE latitude IS NOT NULL), COUNT(*) FROM listings"
    ).fetchone()
    pct = 100 * geo[0] / geo[1] if geo[1] else 0
    (ok if pct >= 80 else warn)(f"geocoded: {geo[0]}/{geo[1]} ({pct:.0f}%)")

    if counts.get("auto_underwriting") is not None:
        uw = conn.execute(
            "SELECT COUNT(*) FROM auto_underwriting au "
            "JOIN listings l ON l.id = au.listing_id").fetchone()[0]
        pct = 100 * uw / geo[1] if geo[1] else 0
        info(f"auto-underwritten: {uw}/{geo[1]} ({pct:.0f}%)")

        scored = conn.execute(
            "SELECT COUNT(*), AVG(score)::int, MAX(score) FROM auto_underwriting "
            "WHERE score IS NOT NULL").fetchone()
        if scored[0]:
            info(f"scored: {scored[0]} deals, avg {scored[1]}, best {scored[2]}")

    if counts.get("listing_history"):
        recent = conn.execute(
            "SELECT field, COUNT(*) FROM listing_history GROUP BY field "
            "ORDER BY COUNT(*) DESC LIMIT 5").fetchall()
        info("history events: " + ", ".join(f"{f}={c}" for f, c in recent))


# =====================================================================
# 6. Gmail -- the outage hypothesis
# =====================================================================
def check_gmail():
    hdr("6. GMAIL OAUTH  (the suspected cause of the outage)")
    try:
        from ingest.gmail_client import service, label_id
    except Exception as e:
        bad(f"import failed: {e}")
        return

    try:
        svc = service()
        labels = svc.users().labels().list(userId="me").execute().get("labels", [])
        ok(f"token VALID -- {len(labels)} labels visible")

        want = os.environ.get("GMAIL_DEAL_FLOW_LABEL", "Deal Flow")
        if label_id(svc, want):
            ok(f"label '{want}' found")
        else:
            warn(f"label '{want}' NOT found -- ingestion would raise RuntimeError")
        info("So the token is not the problem; check ANTHROPIC_API_KEY below.")
    except Exception as e:
        msg = str(e)
        if "invalid_grant" in msg or "expired or revoked" in msg:
            bad("REFRESH TOKEN EXPIRED / REVOKED  <-- this is the outage")
            info("Cause: the OAuth consent screen is in Testing status, which")
            info("expires refresh tokens after 7 days. Token minted ~Jun 22,")
            info("ingestion died Jun 30. That is the 7-day boundary.")
            info("")
            info("Fix (permanent):")
            info("  1. Google Cloud Console -> OAuth consent screen -> PUBLISH APP")
            info("  2. python scripts/gmail_auth.py   (needs client_secret.json)")
            info("  3. Copy the new GMAIL_REFRESH_TOKEN into BOTH Railway services")
        else:
            bad(f"{type(e).__name__}: {msg[:200]}")


# =====================================================================
# 7. Anthropic -- the alternative hypothesis
# =====================================================================
def check_anthropic():
    hdr("7. ANTHROPIC API")
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        bad("ANTHROPIC_API_KEY not set")
        return
    try:
        import anthropic
        models = anthropic.Anthropic(api_key=key).models.list(limit=1)
        ok(f"key valid (models.list returned {len(models.data)})")
        info(f"configured model: {os.environ.get('CLAUDE_MODEL', 'unset')}")
    except Exception as e:
        msg = str(e)
        if "authentication" in msg.lower() or "401" in msg:
            bad("API KEY INVALID OR REVOKED  <-- could also explain the outage")
        elif "credit" in msg.lower() or "quota" in msg.lower() or "429" in msg:
            bad("OUT OF CREDIT / RATE LIMITED  <-- could also explain the outage")
        else:
            bad(f"{type(e).__name__}: {msg[:200]}")


# =====================================================================
def main():
    print(f"\n{'#' * 70}\n#  RTP DEAL INTELLIGENCE -- HEALTH CHECK  (read-only)\n{'#' * 70}")

    if not check_env():
        print(f"\n{RED}Cannot continue without a complete .env.{RESET}\n")
        return 1

    conn = check_db()
    if conn:
        tables, _ = check_schema(conn)
        counts = check_data(conn, tables)
        check_quality(conn, counts)
        conn.close()

    check_gmail()
    check_anthropic()

    hdr("SUMMARY")
    fails = [m for lvl, m in findings if lvl == "fail"]
    warns = [m for lvl, m in findings if lvl == "warn"]
    if not fails and not warns:
        print(f"  {GREEN}Everything healthy.{RESET}")
    for m in fails:
        print(f"  {RED}FAIL{RESET} {m}")
    for m in warns:
        print(f"  {YELLOW}WARN{RESET} {m}")
    print()
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
