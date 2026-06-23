"""Phase 2 step 4 — AI deal summary that READS THE SOURCE email/OM text.
Surfaces the qualitative signals the metrics miss: condition / deferred maintenance,
seller motivation, below-market rents, unit-mix quality, anything notable. 2-3
sentences, direct, no filler. The numbers are passed as context so the summary
complements (not repeats) them."""
import os
import re

from ingest import gmail_client as gc
from ingest.parsers import _client, html_to_text

SYSTEM = ("You write ultra-terse triage bullets for a multifamily investor scanning "
          "deals fast. Surface only what changes a decision — value-add upside, seller "
          "motivation, condition/risk, below-market rents, real data gaps.")

PROMPT = """Deal: {name}, {city} {state} — {units} units, ask {ask}. Metrics: {metrics}.

From the broker's own words below, output UP TO 3 ultra-terse bullets (max ~8 words
each), most decision-relevant first. Telegraphic style, no full sentences, no bullet
characters — one signal per line. If there is genuinely nothing notable to flag (e.g. a
bare MLS notification with no real detail), output NOTHING AT ALL.

SOURCE:
\"\"\"
{src}
\"\"\""""


def _source_text(conn, svc, deal):
    """Gather source text: listing notes + raw_data highlights + Gmail thread body.
    For packages, aggregate member listings."""
    if deal["deal_kind"] == "package":
        rows = conn.execute(
            "SELECT notes, raw_email_id, raw_data FROM listings WHERE package_id=%s",
            (deal["deal_id"],)).fetchall()
    else:
        rows = conn.execute(
            "SELECT notes, raw_email_id, raw_data FROM listings WHERE id=%s",
            (deal["deal_id"],)).fetchall()
    chunks, seen_threads = [], set()
    for notes, thread, raw in rows:
        if notes:
            chunks.append(f"NOTES: {notes}")
        if raw:
            for k in ("unit_mix", "buy_box_fit_sheet"):
                if raw.get(k):
                    chunks.append(f"{k}: {raw[k]}")
        if thread and svc and thread not in seen_threads:
            seen_threads.add(thread)
            body = gc.thread_text(svc, thread)
            if body.strip():
                chunks.append("EMAIL:\n" + re.sub(r"\n{3,}", "\n\n", body))
    return "\n".join(chunks)[:9000]


def summarize(conn, svc, deal, au, model=None):
    src = _source_text(conn, svc, deal)
    if not src.strip():
        return ""  # nothing to say -> leave blank
    model = model or os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
    ask = f"${deal['effective_ask_cents']/100:,.0f}" if deal.get("effective_ask_cents") else "n/a"
    metrics = []
    if au.get("implied_cap_current") is not None:
        metrics.append(f"current cap {float(au['implied_cap_current'])*100:.1f}%")
    if au.get("estimated_dscr") is not None:
        metrics.append(f"DSCR {float(au['estimated_dscr']):.2f}")
    if au.get("price_per_unit_vs_market") is not None:
        metrics.append(f"PPU {float(au['price_per_unit_vs_market'])*100:+.0f}% vs market")
    metrics.append(f"score {au.get('score')}/{au.get('tier')}/{au.get('score_confidence')} conf")

    resp = _client().messages.create(
        model=model, max_tokens=160, system=SYSTEM,
        messages=[{"role": "user", "content": PROMPT.format(
            name=deal["name"], city=deal["market"], state=deal["state"],
            units=deal["effective_units"], ask=ask,
            metrics=", ".join(metrics), src=src)}],
    )
    raw = resp.content[0].text.strip()
    # normalize to clean bullet lines; blank if the model had nothing to say
    lines = []
    for ln in raw.splitlines():
        ln = ln.strip().lstrip("-•*").strip()
        if ln and ln.lower() not in ("none", "nothing", "n/a", "(none)"):
            lines.append(ln)
    # a single "bare MLS notification / nothing to flag" line is filler -> blank
    if len(lines) == 1 and re.search(
            r"\b(bare|nothing to flag|no (?:property )?(?:details|data|info|commentary)|"
            r"notification|no broker)\b", lines[0], re.I):
        return ""
    return "\n".join(lines[:3])
