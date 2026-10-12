"""Exceptions-only daily note (replaces the full RTP Deal Briefing email; Ben 10/12/26:
"I just care that things being sent to my inbox are logged somewhere").

Sent only when there is something that needs a human: a scheduled job that did not run, the
review queue, an offer whose acceptance date passed with no answer, action items due in the
next 3 days, and new in-corridor leads that already have a synced model. Otherwise nothing is
sent and a job_runs row records "quiet".
"""
import datetime as dt
import html
import os

from ingest import gmail_client as gc


def gather(conn):
    q = lambda sql, *p: conn.execute(sql, p).fetchall()
    d = {}
    d["jobs_missing"] = q("SELECT job, expected_every::text, last_ok, last_status FROM v_jobs_missing WHERE job <> 'tracker_export'")
    d["review"] = q("SELECT kind, count(*) FROM review_queue WHERE status='open' GROUP BY 1 ORDER BY 2 DESC")
    d["needs_review"] = q("SELECT count(*) FROM listings WHERE status='needs_review'")[0][0]
    d["offers_overdue"] = q(
        "SELECT o.id, COALESCE(l.address, pk.name) AS name, o.offer_type, o.offer_date, o.price_cents, o.terms->>'acceptance_date' AS acc "
        "FROM offers o LEFT JOIN listings l ON l.id=o.listing_id LEFT JOIN packages pk ON pk.id=o.package_id "
        "WHERE o.response='pending' AND (o.terms->>'acceptance_date')::date < CURRENT_DATE ORDER BY o.offer_date")
    d["actions_due"] = q(
        "SELECT title, due_on, COALESCE(about_person, about_org, about_listing, about_package, about_property, '') FROM v_action_items_open "
        "WHERE due_on <= CURRENT_DATE + 3 ORDER BY due_on")
    d["new_leads"] = q(
        "SELECT l.id, l.address, l.city, l.units, l.asking_price, l.broker_name, au.model_file "
        "FROM listings l JOIN auto_underwriting au ON au.listing_id=l.id "
        "WHERE l.status='lead' AND au.model_stats IS NOT NULL AND l.date_ingested > now() - interval '1 day'")
    d["ingest_24h"] = q(
        "SELECT count(*), count(*) FILTER (WHERE status='lead'), count(*) FILTER (WHERE sale_price IS NOT NULL) "
        "FROM listings WHERE date_ingested > now() - interval '1 day'")[0]
    return d


def needs_attention(d):
    return bool(d["jobs_missing"] or d["review"] or d["needs_review"] or d["offers_overdue"] or d["actions_due"] or d["new_leads"])


def render(d):
    e = html.escape
    usd = lambda c: f"${c/100:,.0f}" if c else "n/a"
    parts = ["<div style='font:14px/1.5 Inter,Arial,sans-serif;color:#14202e;max-width:640px'>"]
    n, leads, sold = d["ingest_24h"]
    parts.append(f"<p style='color:#6B7280'>Logged in the last 24h: {n} listings ({leads} leads, {sold} sales). Nothing below needs you unless listed.</p>")
    if d["jobs_missing"]:
        parts.append("<h3 style='color:#b0503f'>Jobs that did not run</h3><ul>")
        for job, every, last_ok, last_status in d["jobs_missing"]:
            parts.append(f"<li><b>{e(job)}</b> (expected every {e(every)}): last ok {last_ok:%m/%d %H:%M} UTC, last status {e(str(last_status))}</li>" if last_ok
                         else f"<li><b>{e(job)}</b> (expected every {e(every)}): never recorded</li>")
        parts.append("</ul>")
    if d["offers_overdue"]:
        parts.append("<h3>Offers past their acceptance date, no answer logged</h3><ul>")
        for oid, name, typ, date, price, acc in d["offers_overdue"]:
            parts.append(f"<li>#{oid} {e(name)}: {e(typ)} {date:%m/%d} {usd(price)}, acceptance {e(acc)}. Reply or log the response.</li>")
        parts.append("</ul>")
    if d["actions_due"]:
        parts.append("<h3>Due in the next 3 days</h3><ul>")
        for title, due, about in d["actions_due"]:
            parts.append(f"<li>{due:%m/%d}: {e(title)}" + (f" ({e(about)})" if about else "") + "</li>")
        parts.append("</ul>")
    if d["new_leads"]:
        parts.append("<h3>New leads with a synced model</h3><ul>")
        for lid, addr, city, units, ask, broker, mf in d["new_leads"]:
            parts.append(f"<li>#{lid} {e(addr)}, {e(city)}: {units}u {usd(ask)} ({e(broker or '')}) model {e(mf or '')}</li>")
        parts.append("</ul>")
    if d["review"] or d["needs_review"]:
        parts.append("<h3>Waiting in the review queue</h3><ul>")
        for kind, cnt in d["review"]:
            parts.append(f"<li>{cnt} {e(kind.replace('_', ' '))}</li>")
        if d["needs_review"]:
            parts.append(f"<li>{d['needs_review']} listings at needs_review</li>")
        parts.append("</ul><p style='color:#6B7280'>Clear them in the dashboard Inbox tab.</p>")
    parts.append("</div>")
    return "\n".join(parts)


def run(conn, svc=None, send=False, to=None, preview_path=None):
    d = gather(conn)
    attention = needs_attention(d)
    body = render(d)
    subject = "RTP exceptions: " + (", ".join(k for k, v in (("jobs", d["jobs_missing"]), ("offers", d["offers_overdue"]),
                                                              ("due", d["actions_due"]), ("leads", d["new_leads"]),
                                                              ("review", d["review"] or d["needs_review"])) if v) or "quiet")
    if preview_path:
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(body)
    sent_id = None
    if send and attention:
        to = to or os.environ.get("DISPATCH_EMAIL")
        sent_id = gc.send_html(svc, to, subject, body)
    return {"subject": subject, "attention": attention, "sent_id": sent_id,
            "counts": {k: (len(v) if isinstance(v, list) else v) for k, v in d.items() if k != "ingest_24h"}}
