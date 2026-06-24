"""Daily briefing — push new leads / changes / needs-review to Ben's inbox.
Leads with TIER + AI summary first (score de-emphasized, per the calibration decisions);
price cuts flagged prominently (motivated-seller signal). Covers everything since a
tracked last_briefed_at so deals never repeat; the timestamp advances only on a real send.
"""
import os
import re

from ingest import gmail_client as gc

GMAIL_THREAD = "https://mail.google.com/mail/u/0/#all/"
PIPELINE_STATUSES = ("lead", "underwriting", "under_contract", "needs_review")


def _usd(cents):
    return f"${cents/100:,.0f}" if cents is not None else "n/a"


def short_summary(text, max_sentences=2):
    """Strip markdown and trim the full DB summary to a 1-2 sentence email lead.
    Drops a leading 'Triage Note — ...' header line if present."""
    if not text:
        return ""
    t = text.replace("*", "").replace("__", "")  # strip markdown bold/italic markers
    lines = [l.strip() for l in t.splitlines() if l.strip()]
    if lines and lines[0].lower().startswith(("triage note", "bottom line")):
        lines = lines[1:]
    body = re.sub(r"\s+", " ", " ".join(lines)).strip()
    sentences = re.split(r"(?<=[.!?])\s+", body)
    return " ".join(sentences[:max_sentences]).strip()


def get_since(conn):
    """last_briefed_at, or 30 days ago on first run (so the first briefing has content)."""
    return conn.execute(
        "SELECT COALESCE((SELECT value::timestamptz FROM system_meta "
        "WHERE key='last_briefed_at'), NOW() - INTERVAL '30 days')").fetchone()[0]


def gather(conn, since):
    # leads ordered exactly like v_pipeline_deals: tier -> confidence -> score
    new_leads = conn.execute(
        """SELECT d.deal_kind, d.deal_id, d.name, d.market, d.state, d.effective_units,
                  d.effective_ask, d.score, d.tier, d.score_confidence, d.summary,
                  l.raw_email_id
           FROM v_pipeline_deals d
           LEFT JOIN listings l ON d.deal_kind='listing' AND l.id=d.deal_id
           LEFT JOIN packages p ON d.deal_kind='package' AND p.id=d.deal_id
           WHERE COALESCE(l.date_ingested, p.created_at) > %s
           ORDER BY CASE d.tier WHEN 'Priority' THEN 0 WHEN 'Watch' THEN 1
                                WHEN 'Pass' THEN 2 ELSE 3 END,
                    CASE d.score_confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1
                                            WHEN 'low' THEN 2 ELSE 3 END,
                    d.score DESC NULLS LAST""", (since,)).fetchall()

    changes = conn.execute(
        """SELECT l.id, l.address, l.city, l.state, l.units, l.asking_price, l.status,
                  lh.field, lh.old_value, lh.new_value
           FROM listing_history lh JOIN listings l ON l.id = lh.listing_id
           WHERE lh.changed_at > %s
             AND ((lh.field='asking_price' AND lh.old_value IS NOT NULL) OR lh.field='status')
           ORDER BY lh.changed_at DESC""", (since,)).fetchall()

    enrich_n = conn.execute(
        "SELECT count(*) FROM listing_history WHERE changed_at > %s "
        "AND field NOT IN ('asking_price','status')", (since,)).fetchone()[0]

    needs_review = conn.execute(
        "SELECT address, city, state, units, asking_price, "
        "raw_data->'routing_reasons'->>0 FROM listings WHERE status='needs_review' "
        "ORDER BY state, city").fetchall()

    # cols: 0 id,1 addr,2 city,3 state,4 units,5 ask,6 status,7 field,8 old,9 new
    # aged-out leads (lead -> stale demotions) get their own line — not comps
    aged_out = [c for c in changes if c[7] == "status" and c[9] == "stale" and c[8] == "lead"]
    rest = [c for c in changes if c not in aged_out]
    pipeline_changes = [c for c in rest if c[6] in PIPELINE_STATUSES]
    market_changes = [c for c in rest if c[6] not in PIPELINE_STATUSES]
    price_cuts = [c for c in rest if c[7] == "asking_price" and int(c[9]) < int(c[8])]
    return {"new_leads": new_leads, "pipeline_changes": pipeline_changes,
            "market_changes": market_changes, "price_cuts": price_cuts, "aged_out": aged_out,
            "enrich_n": enrich_n, "needs_review": needs_review}


def _maps_link(name, market, state):
    from urllib.parse import quote_plus
    q = name if (name and name.lower() not in ("unknown", "?")) else ""
    query = quote_plus(f"{q} {market or ''} {state or ''}".strip())
    label = f"{name or '?'}, {market} {state}"
    return (f'<a href="https://www.google.com/maps/search/?api=1&query={query}" '
            f'style="color:#111;text-decoration:none;border-bottom:1px dotted #999">{label}</a>')


def _lead_card(r):
    kind, did, name, market, state, units, ask, score, tier, conf, summary, thread = r
    ppu = _usd(ask / units) if (ask and units) else "n/a"
    color = {"Priority": "#0b7", "Watch": "#e90", "Pass": "#999"}.get(tier, "#999")
    idtag = f"pkg {did}" if kind == "package" else f"id {did}"
    link = (f' · <a href="{GMAIL_THREAD}{thread}" style="color:#36c;text-decoration:none">email ↗</a>'
            if thread else "")
    bullets = [b for b in (summary or "").splitlines() if b.strip()]
    bullets_html = ("<ul style=\"margin:6px 0 0;padding-left:18px;color:#333;font-size:13px;"
                    "line-height:1.5\">" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>"
                    ) if bullets else ""
    return f"""
    <tr><td style="padding:12px 14px;border-bottom:1px solid #eee">
      <span style="background:{color};color:#fff;font-size:11px;font-weight:700;
        padding:2px 8px;border-radius:10px">{tier}</span>
      <span style="font-weight:600;font-size:15px;margin-left:6px">{_maps_link(name, market, state)}</span>
      <span style="color:#888;font-size:12px;margin-left:8px">
        {units or '?'} units · {_usd(ask)} · {ppu}/unit{link}</span>
      {bullets_html}
      <div style="color:#bbb;font-size:11px;margin-top:5px">{idtag} · {conf or '?'} conf · score {score if score is not None else '–'}</div>
    </td></tr>"""


def render_html(data, since):
    nl, pc, nr = data["new_leads"], data["price_cuts"], data["needs_review"]
    pipe_ch, mkt_ch, aged = data["pipeline_changes"], data["market_changes"], data["aged_out"]
    header = (f"{len(nl)} new lead{'s'*(len(nl)!=1)} · {len(pc)} price cut{'s'*(len(pc)!=1)} "
              f"· {len(nr)} needs review")

    if not nl and not pipe_ch and not mkt_ch and not aged and not nr:
        return (f'<div style="font-family:system-ui,Arial">'
                f'<h2>RTP Deal Briefing</h2><p>No new deals or changes today.</p></div>'), header

    parts = [f'<div style="font-family:system-ui,-apple-system,Arial;max-width:680px;color:#222">',
             f'<h2 style="margin:0 0 2px">RTP Deal Briefing</h2>',
             f'<div style="color:#666;font-size:13px;margin-bottom:16px">{header}'
             f' · since {since:%Y-%m-%d %H:%M}</div>']

    if nl:
        parts.append('<h3 style="font-size:14px;color:#444;margin:18px 0 6px">NEW LEADS</h3>'
                     '<table style="width:100%;border-collapse:collapse;border:1px solid #eee">')
        parts.extend(_lead_card(r) for r in nl)
        parts.append('</table>')

    def change_rows(rows):
        out = []
        for c in rows:
            _id, addr, city, st, units, ask, status, field, old, new = c
            if field == "asking_price":
                cut = int(new) < int(old)
                arrow = "▼" if cut else "▲"
                col = "#c33" if cut else "#888"
                out.append(f'<li style="font-size:13px;margin:3px 0">'
                           f'<b style="color:{col}">{arrow} price {"cut" if cut else "rise"}</b> '
                           f'{addr}, {city} {st}: {_usd(int(old))} → {_usd(int(new))}</li>')
            else:
                out.append(f'<li style="font-size:13px;margin:3px 0">status: {addr}, {city} {st}: '
                           f'{old} → {new}</li>')
        return out

    def aged_label(c):
        _id, addr, city, st, units, ask = c[0], c[1], c[2], c[3], c[4], c[5]
        who = addr if (addr and addr.lower() not in ("unknown", "?")) else f"{units or '?'}-unit"
        return f"#{_id} {who}, {city} ({_usd(ask)})"

    if pipe_ch:
        parts.append('<h3 style="font-size:14px;color:#444;margin:20px 0 6px">'
                     'CHANGES — YOUR PIPELINE</h3><ul style="margin:0;padding-left:18px">')
        parts.extend(change_rows(pipe_ch))
        parts.append('</ul>')
    if mkt_ch:
        parts.append('<h3 style="font-size:14px;color:#888;margin:20px 0 6px">'
                     'MARKET MOVES (COMPS)</h3>'
                     '<ul style="margin:0;padding-left:18px;color:#777">')
        parts.extend(change_rows(mkt_ch))
        parts.append('</ul>')
    if data["enrich_n"]:
        parts.append(f'<div style="color:#999;font-size:12px;margin-top:4px">'
                     f'+ {data["enrich_n"]} field enrichment(s) across deals</div>')

    if aged:
        items = "".join(f"<li>{aged_label(a)}</li>" for a in aged)
        parts.append(f'<div style="color:#999;font-size:12px;margin-top:14px">'
                     f'<b style="color:#777">AGED OUT ({len(aged)})</b> — leads gone quiet past '
                     f'the active window, now comps:'
                     f'<ul style="margin:4px 0 0;padding-left:18px">{items}</ul></div>')

    if nr:
        parts.append('<h3 style="font-size:14px;color:#444;margin:20px 0 6px">'
                     f'NEEDS REVIEW ({len(nr)})</h3><ul style="margin:0;padding-left:18px">')
        for addr, city, st, units, ask, reason in nr:
            parts.append(f'<li style="font-size:13px;margin:3px 0">{addr or "?"}, {city} {st} '
                         f'· {units or "?"} units · {_usd(ask)} '
                         f'<span style="color:#999">— {reason or ""}</span></li>')
        parts.append('</ul>')

    parts.append(
        '<div style="color:#aaa;font-size:12px;margin-top:22px;border-top:1px solid #eee;'
        'padding-top:10px">Prune from your phone: <b>reply</b> to this email with '
        '<b>kill</b> + the ids (e.g. <code>kill 24, 25</code>) to drop those deals.</div>')
    parts.append('</div>')
    return "\n".join(parts), header


def run(conn, svc=None, send=False, to=None, preview_path=None, since_override=None):
    since = since_override or get_since(conn)
    data = gather(conn, since)
    rendered = render_html(data, since)
    html, header = rendered if isinstance(rendered, tuple) else (rendered, "quiet day")
    subject = f"RTP Deal Briefing — {header}"

    if preview_path:
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(html)
    sent_id = None
    if send:
        to = to or os.environ.get("DISPATCH_EMAIL")
        sent_id = gc.send_html(svc, to, subject, html)
        conn.execute(
            "INSERT INTO system_meta (key, value, updated_at) "
            "VALUES ('last_briefed_at', NOW()::text, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value=NOW()::text, updated_at=NOW()")
        conn.commit()
    return {"since": since, "subject": subject, "counts": header,
            "data": data, "sent_id": sent_id}
