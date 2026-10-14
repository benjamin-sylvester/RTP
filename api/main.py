"""RTP dashboard API — slice 1: read endpoints (list-deals, deal-detail, comps).
Reads v_deal_board (package-aware, scored) + the underlying tables. Money stays in
cents; the frontend formats. No auth yet (slice 2), no frontend (slice 3+)."""
import os
import pathlib
import secrets

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from starlette.middleware.sessions import SessionMiddleware

from api import db
from api.auth import check_password, require_auth
from ingest import freshness
from ingest.gmail_client import _load_env

_load_env()
app = FastAPI(title="RTP Deal Dashboard API", version="0.1")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("DASHBOARD_SECRET_KEY") or secrets.token_hex(32),
    same_site="lax",
    https_only=os.environ.get("DASHBOARD_HTTPS", "").lower() in ("1", "true"),
)


@app.post("/api/login")
def login(request: Request, password: str = Body(..., embed=True)):
    if not check_password(password):
        raise HTTPException(status_code=401, detail="wrong password")
    request.session["authed"] = True
    return {"ok": True}


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


_STATIC = pathlib.Path(__file__).parent / "static"


@app.get("/")
def index():
    return FileResponse(_STATIC / "index.html")

ACTIVE = ["lead", "underwriting", "loi_sent", "under_contract"]
SORTABLE = {  # whitelist -> column
    "score": "score", "units": "effective_units", "ask": "effective_ask",
    "ppu": "price_per_unit", "last_seen": "last_seen_at", "market": "market",
}
# default ordering = same as the briefing: tier -> confidence -> score
DEFAULT_ORDER = (
    "CASE tier WHEN 'Priority' THEN 0 WHEN 'Watch' THEN 1 WHEN 'Pass' THEN 2 ELSE 3 END, "
    "CASE score_confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 3 END, "
    "score DESC NULLS LAST")


@app.get("/api/health")
def health():
    return {"ok": True, "deals": db.one("SELECT count(*) AS n FROM v_deal_board")["n"]}


@app.get("/api/deals")
def list_deals(
    tier: str | None = None,
    city: str | None = None,
    units_min: int | None = None,
    units_max: int | None = None,
    score_min: int | None = None,
    status: str | None = Query(None, description="comma list; overrides default active set"),
    comps: bool = False, needs_review: bool = False, closed: bool = False,
    owned: bool = False, quiet: bool = False, hide_unknown: bool = True,
    sort: str = "default", order: str = "desc",
    limit: int = 200, offset: int = 0,
    _auth=Depends(require_auth),
):
    # status set: explicit param wins ('all' = every status); legacy toggles still work
    if status == "all":
        statuses = list(freshness.VALID)
        quiet = True
    elif status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
    else:
        statuses = list(ACTIVE)
        if comps:
            statuses.append("comp_only")
        if needs_review:
            statuses.append("needs_review")
        if closed:
            statuses += ["passed", "lost"]
        if owned:
            statuses.append("owned")

    # recency: only LEADS must be seen within active_lead_days to count as active (a lead
    # gone quiet drops out by date). Manually-advanced deals (underwriting+) and comps/passed
    # are never time-filtered. `quiet=true` or an explicit status set disables the filter.
    where = ["status = ANY(%s)",
             "(%s OR status <> 'lead' OR last_seen_at > NOW() - make_interval(days => %s))"]
    params: list = [statuses, (quiet or bool(status)), freshness.active_lead_days()]
    if hide_unknown and status != "needs_review":  # rows the parser could not place (Ben, 10/13)
        where.append("NOT (lower(name) LIKE 'unknown%%' OR lower(name) LIKE '%%addr tbd%%' OR lower(name) LIKE '%%(address%%')")
    if tier:
        where.append("tier = %s"); params.append(tier)
    if city:
        where.append("lower(market) LIKE %s"); params.append(f"%{city.lower()}%")
    if units_min is not None:
        where.append("effective_units >= %s"); params.append(units_min)
    if units_max is not None:
        where.append("effective_units <= %s"); params.append(units_max)
    if score_min is not None:
        where.append("score >= %s"); params.append(score_min)

    if sort in SORTABLE:
        order_by = f"{SORTABLE[sort]} {'ASC' if order == 'asc' else 'DESC'} NULLS LAST"
    else:
        order_by = DEFAULT_ORDER

    sql = (f"SELECT * FROM v_deal_board WHERE {' AND '.join(where)} "
           f"ORDER BY {order_by} LIMIT %s OFFSET %s")
    params += [min(limit, 500), offset]
    rows = db.query(sql, params)
    return {"count": len(rows), "filters": {
        "statuses": statuses, "tier": tier, "city": city,
        "units_min": units_min, "units_max": units_max, "score_min": score_min,
        "sort": sort if sort in SORTABLE else "default"}, "deals": rows}


@app.get("/api/pipeline")
def pipeline(_auth=Depends(require_auth)):
    """Live deals = the ones RTP is actually underwriting or bidding on (manual statuses
    underwriting / loi_sent / under_contract), listings AND packages. Leads are not live
    (Ben, 10/13/26): they stay in the Deals tab; the count is returned so the Live tab can say so."""
    rows = db.query(
        "SELECT * FROM ("
        "SELECT 'listing' AS deal_kind, l.id, l.address, l.city, l.state, l.units, l.asking_price, l.price_per_unit, "
        "  l.year_built, l.status, l.source, l.broker_name, l.broker_email, l.account, "
        "  l.drive_folder_id, l.uw_folder, l.latitude, l.longitude, "
        "  au.model_file, au.model_version, au.model_synced_at, au.model_stats, "
        "  au.implied_cap_current, au.implied_cap_stabilized, au.score, au.tier, "
        "  (SELECT count(*) FROM offers o WHERE o.listing_id=l.id) AS offers, "
        "  (SELECT max(o.offer_date) FROM offers o WHERE o.listing_id=l.id) AS last_offer_date "
        "FROM listings l LEFT JOIN auto_underwriting au ON au.listing_id = l.id "
        "WHERE l.status IN ('underwriting','loi_sent','under_contract') "
        "  AND l.package_id IS NULL AND l.merged_into_id IS NULL "
        "UNION ALL "
        "SELECT 'package', p.id, p.name, p.market, p.state, "
        "  COALESCE(p.total_units, (SELECT sum(units) FROM listings m WHERE m.package_id=p.id)), "
        "  COALESCE(p.asking_price, (SELECT sum(asking_price) FROM listings m WHERE m.package_id=p.id)), NULL, NULL, "
        "  p.status, 'package', p.broker_name, p.broker_email, NULL, p.drive_folder_id, NULL, NULL, NULL, "
        "  au.model_file, au.model_version, au.model_synced_at, au.model_stats, "
        "  au.implied_cap_current, au.implied_cap_stabilized, au.score, au.tier, "
        "  (SELECT count(*) FROM offers o WHERE o.package_id=p.id), "
        "  (SELECT max(o.offer_date) FROM offers o WHERE o.package_id=p.id) "
        "FROM packages p LEFT JOIN auto_underwriting au ON au.package_id = p.id "
        "WHERE p.status IN ('underwriting','loi_sent','under_contract') "
        ") t ORDER BY CASE t.status WHEN 'under_contract' THEN 0 WHEN 'loi_sent' THEN 1 ELSE 2 END, t.units DESC NULLS LAST")
    leads = db.one("SELECT count(*) AS n FROM listings WHERE status='lead' AND package_id IS NULL AND merged_into_id IS NULL "
                   "AND last_seen_at > NOW() - make_interval(days => %s)", (freshness.active_lead_days(),))["n"]
    return {"count": len(rows), "deals": rows, "leads": leads}


@app.get("/api/map")
def map_data(_auth=Depends(require_auth)):
    """Every tracked property with the fields the Map + Analytics tabs slice on:
    price/unit, cap (financials or synced model), tier, score, ingest date."""
    rows = db.query(
        "SELECT l.id, l.address, l.city, l.state, l.units, l.price_per_unit, l.asking_price, "
        "  l.status, l.account, l.source, l.year_built, l.latitude, l.longitude, "
        "  l.date_ingested, lf.cap_rate AS lf_cap, au.implied_cap_current AS au_cap, "
        "  au.tier, au.score, (au.model_stats IS NOT NULL) AS has_model "
        "FROM listings l "
        "LEFT JOIN listing_financials lf ON lf.listing_id = l.id "
        "LEFT JOIN auto_underwriting au ON au.listing_id = l.id "
        "WHERE l.package_id IS NULL AND l.merged_into_id IS NULL")
    return {"count": len(rows), "listings": rows}


@app.get("/api/deals/{kind}/{deal_id}")
def deal_detail(kind: str, deal_id: int, _auth=Depends(require_auth)):
    board = db.one("SELECT * FROM v_deal_board WHERE deal_kind=%s AND deal_id=%s",
                   (kind, deal_id))
    if not board:
        raise HTTPException(404, "deal not found")
    key = "package_id" if kind == "package" else "listing_id"
    au = db.one(f"SELECT * FROM auto_underwriting WHERE {key}=%s", (deal_id,))

    detail = {"deal": board, "underwriting": au}
    if kind == "listing":
        detail["listing"] = db.one(
            "SELECT id, address, city, state, zip, units, asking_price, price_per_unit, "
            "sale_price, sale_price_per_unit, sale_date, "
            "year_built, building_sf, property_class, source, broker_name, broker_email, "
            "listing_date, last_seen_at, notes, drive_folder_id, om_url, boe_url, raw_email_id "
            "FROM listings WHERE id=%s", (deal_id,))
        detail["financials"] = db.one(
            "SELECT * FROM listing_financials WHERE listing_id=%s", (deal_id,))
        detail["unit_mix"] = db.query(
            "SELECT unit_type, count, avg_sf, avg_rent, market_rent, rent_delta_pct "
            "FROM unit_mix WHERE listing_id=%s ORDER BY id", (deal_id,))
        detail["history"] = db.query(
            "SELECT field, old_value, new_value, changed_at FROM listing_history "
            "WHERE listing_id=%s ORDER BY changed_at DESC, id DESC", (deal_id,))
        thread = (detail["listing"] or {}).get("raw_email_id")
        detail["links"] = {
            "gmail_thread": f"https://mail.google.com/mail/u/0/#all/{thread}" if thread else None,
            "drive_folder_id": (detail["listing"] or {}).get("drive_folder_id"),
            "om_url": (detail["listing"] or {}).get("om_url"),
            "boe_url": (detail["listing"] or {}).get("boe_url"),
        }
    else:  # package: its member parcels
        detail["members"] = db.query(
            "SELECT id, address, city, units, asking_price, status, last_seen_at "
            "FROM listings WHERE package_id=%s ORDER BY address", (deal_id,))
    # Phase 1: offers, broker interactions, documents, property history (all optional tables)
    try:
        detail["offers"] = db.query(
            "SELECT o.id, o.offer_type, o.direction, o.offer_date, o.price_cents, o.terms, o.response, "
            "o.response_date, o.response_notes, o.notes, p.full_name AS sent_to "
            f"FROM offers o LEFT JOIN people p ON p.id=o.sent_to_person_id WHERE o.{key}=%s "
            "ORDER BY o.offer_date DESC, o.id DESC", (deal_id,))
        detail["interactions"] = db.query(
            "SELECT i.occurred_at, i.channel, i.direction, i.summary, p.full_name AS person "
            f"FROM interactions i LEFT JOIN people p ON p.id=i.person_id WHERE i.{key}=%s "
            "ORDER BY i.occurred_at DESC LIMIT 20", (deal_id,))
        detail["documents"] = db.query(
            "SELECT id, title, doc_type, doc_date, version, drive_url, drive_file_id "
            f"FROM documents WHERE {key}=%s ORDER BY doc_date DESC NULLS LAST, id DESC", (deal_id,))
        if kind == "listing":
            detail["broker"] = db.one(
                "SELECT p.id, p.full_name, p.phone, o.name AS firm, "
                "(SELECT max(occurred_at) FROM interactions i WHERE i.person_id=p.id) AS last_interaction, "
                "(SELECT summary FROM interactions i WHERE i.person_id=p.id ORDER BY occurred_at DESC LIMIT 1) AS last_summary "
                "FROM listings l JOIN people p ON p.id=l.broker_person_id LEFT JOIN organizations o ON o.id=p.org_id "
                "WHERE l.id=%s", (deal_id,))
            detail["property_history"] = db.query(
                "SELECT event_kind, event_at, ref_id, detail_status, amount_cents, detail "
                "FROM v_property_history WHERE property_id=(SELECT property_id FROM listings WHERE id=%s) "
                "ORDER BY event_at", (deal_id,))
    except Exception as e:  # pre-migration database: keep the page working
        detail["phase1_error"] = str(e)[:200]
    return detail


@app.get("/api/investors")
def investors(tier: str | None = None, stale_days: int | None = None, _auth=Depends(require_auth)):
    """LP pipeline (people with lp / lp_prospect / capital_partner roles) with last touch,
    next action and positions. Feeds the Investors tab."""
    where, params = [], []
    if tier:
        where.append("lp_tier = %s"); params.append(tier)
    if stale_days:
        where.append("(last_interaction IS NULL OR last_interaction < now() - make_interval(days => %s))"); params.append(stale_days)
    sql = "SELECT * FROM v_lp_pipeline" + (" WHERE " + " AND ".join(where) if where else "") + \
          " ORDER BY lp_tier NULLS LAST, last_interaction DESC NULLS LAST, full_name"
    rows = db.query(sql, params)
    positions = db.query("SELECT * FROM v_investor_positions")
    entities = db.query("SELECT id, legal_name, short_name, kind, state_of_formation, property_id FROM entities ORDER BY id")
    return {"count": len(rows), "people": rows, "positions": positions, "entities": entities}


def feed(days: int = 3, limit: int = 60):
    """What changed: touches logged, new in-box leads, price cuts and rises on tracked deals,
    closed sales, offer responses, documents added. One list, newest first."""
    items = []
    for r in db.query(
            "SELECT i.occurred_at AS at, i.channel, i.direction, i.summary, i.listing_id, i.package_id, i.person_id, "
            "COALESCE(p.full_name, o.name) AS who, l.address AS listing, pk.name AS package "
            "FROM interactions i LEFT JOIN people p ON p.id=i.person_id LEFT JOIN organizations o ON o.id=i.org_id "
            "LEFT JOIN listings l ON l.id=i.listing_id LEFT JOIN packages pk ON pk.id=i.package_id "
            "WHERE i.occurred_at > now() - make_interval(days => %s) "
            "AND COALESCE(i.source,'') NOT LIKE 'tracker:%%' AND COALESCE(i.source,'') <> 'call_list_seed' "  # historical imports are not news
            "ORDER BY i.occurred_at DESC LIMIT %s", (days, limit)):
        summary = r["summary"] or ""
        if len(summary) > 180:
            summary = summary[:177].rsplit(" ", 1)[0] + "..."
        items.append({"at": r["at"], "kind": "touch", "who": r["who"], "title": summary,
                      "sub": f"{r['channel']} {r['direction']}" + (f" · {r['listing'] or r['package']}" if (r["listing"] or r["package"]) else ""),
                      "listing_id": r["listing_id"], "package_id": r["package_id"], "person_id": r["person_id"]})
    for r in db.query(
            "SELECT l.id, l.address, l.city, l.state, l.units, l.asking_price, l.price_per_unit, l.broker_name, l.date_ingested AS at "
            "FROM listings l WHERE l.status='lead' AND l.merged_into_id IS NULL AND l.package_id IS NULL "
            "AND l.date_ingested > now() - make_interval(days => %s) ORDER BY l.date_ingested DESC LIMIT %s", (days, limit)):
        items.append({"at": r["at"], "kind": "lead", "who": r["broker_name"],
                      "title": f"New lead: {r['address']}, {r['city']}",
                      "sub": f"{r['units'] or '?'} units · {_usd(r['asking_price'])} · {_usd(r['price_per_unit'])}/unit",
                      "listing_id": r["id"]})
    for r in db.query(
            "SELECT h.changed_at AS at, h.field, h.old_value, h.new_value, l.id, l.address, l.city, l.status, l.broker_name "
            "FROM listing_history h JOIN listings l ON l.id=h.listing_id "
            "WHERE h.changed_at > now() - make_interval(days => %s) AND h.old_value IS NOT NULL "
            "AND ((h.field='asking_price' AND l.status IN ('lead','underwriting','loi_sent','under_contract')) "
            "     OR h.field='sale_price' "
            "     OR (h.field='status' AND h.new_value IN ('underwriting','loi_sent','under_contract','owned','lost'))) "
            "ORDER BY h.changed_at DESC LIMIT %s", (days, limit)):
        if r["field"] == "asking_price":
            o, n = int(r["old_value"]), int(r["new_value"])
            kind = "price_cut" if n < o else "price_rise"
            title = f"{'Price cut' if n < o else 'Price rise'}: {r['address']}, {r['city']}"
            sub = f"{_usd(o)} to {_usd(n)}"
        elif r["field"] == "sale_price":
            kind, title, sub = "sold", f"Sold: {r['address']}, {r['city']}", f"{_usd(int(r['new_value']))} executed"
        else:
            kind, title, sub = "status", f"{r['address']}, {r['city']} moved to {r['new_value'].replace('_', ' ')}", f"from {r['old_value']}"
        items.append({"at": r["at"], "kind": kind, "who": r["broker_name"], "title": title, "sub": sub, "listing_id": r["id"]})
    for r in db.query(
            "SELECT o.id, o.offer_type, o.direction, o.price_cents, o.response, o.response_date, o.created_at, o.offer_date, "
            "o.listing_id, o.package_id, COALESCE(l.address, pk.name) AS name, p.full_name AS who "
            "FROM offers o LEFT JOIN listings l ON l.id=o.listing_id LEFT JOIN packages pk ON pk.id=o.package_id "
            "LEFT JOIN people p ON p.id=o.sent_to_person_id "
            "WHERE o.created_at > now() - make_interval(days => %s) OR o.response_date > CURRENT_DATE - %s "
            "ORDER BY o.updated_at DESC LIMIT %s", (days, days, limit)):
        if r["response"] != "pending" and r["response_date"]:
            items.append({"at": r["response_date"], "kind": "offer", "who": r["who"],
                          "title": f"Offer {r['response']}: {r['name']}", "sub": f"{r['offer_type']} {_usd(r['price_cents'])}",
                          "listing_id": r["listing_id"], "package_id": r["package_id"]})
        else:
            items.append({"at": r["created_at"], "kind": "offer", "who": r["who"],
                          "title": f"Offer logged: {r['name']}", "sub": f"{r['offer_type']} {_usd(r['price_cents'])} · {r['response']}",
                          "listing_id": r["listing_id"], "package_id": r["package_id"]})
    for r in db.query(
            "SELECT d.created_at AS at, d.title, d.doc_type, d.listing_id, d.package_id, d.person_id "
            "FROM documents d WHERE d.created_at > now() - make_interval(days => %s) ORDER BY d.created_at DESC LIMIT %s", (days, limit)):
        items.append({"at": r["at"], "kind": "document", "who": None, "title": f"Document: {r['title']}", "sub": r["doc_type"],
                      "listing_id": r["listing_id"], "package_id": r["package_id"], "person_id": r["person_id"]})
    items.sort(key=lambda x: str(x["at"]), reverse=True)
    return items[:limit]


def _usd(cents):
    return f"${cents/100:,.0f}" if cents is not None else "n/a"


@app.get("/api/feed")
def feed_endpoint(days: int = 3, _auth=Depends(require_auth)):
    return {"days": days, "items": feed(days)}


@app.get("/api/inbox")
def inbox(_auth=Depends(require_auth)):
    """Everything waiting for a human: review queue, jobs that did not run, offers past their
    acceptance date, action items due soon, needs_review listings."""
    return {
        "feed": feed(3),
        "jobs_missing": db.query("SELECT job, expected_every::text, last_ok, last_status FROM v_jobs_missing"),
        "job_runs": db.query("SELECT job, started_at, finished_at, status, counts FROM job_runs ORDER BY started_at DESC LIMIT 20"),
        "review": db.query("SELECT id, kind, ref_table, ref_id, payload, created_at FROM review_queue WHERE status='open' ORDER BY created_at DESC"),
        "needs_review": db.query("SELECT id, address, city, state, units, asking_price, source, date_ingested "
                                 "FROM listings WHERE status='needs_review' ORDER BY date_ingested DESC"),
        "offers_overdue": db.query(
            "SELECT o.id, COALESCE(l.address, pk.name) AS name, o.listing_id, o.package_id, o.offer_type, o.offer_date, o.price_cents, "
            "o.terms->>'acceptance_date' AS acceptance_date FROM offers o LEFT JOIN listings l ON l.id=o.listing_id "
            "LEFT JOIN packages pk ON pk.id=o.package_id WHERE o.response='pending' ORDER BY o.offer_date"),
        "actions_due": db.query("SELECT * FROM v_action_items_open WHERE due_on <= CURRENT_DATE + 7 ORDER BY due_on"),
        # split view (Ben, 10/13): to-do = open items due within 14 days or undated; waiting = ball in someone else's court
        "actions_todo": db.query("SELECT * FROM v_action_items_open WHERE status='open' AND due_on <= CURRENT_DATE + 14 ORDER BY due_on, id"),
        "actions_undated": db.query("SELECT * FROM v_action_items_open WHERE status='open' AND due_on IS NULL ORDER BY updated_at DESC, id"),
        "actions_later": db.one("SELECT count(*) AS n FROM v_action_items_open WHERE status='open' AND due_on > CURRENT_DATE + 14")["n"],
        "actions_waiting": db.query("SELECT * FROM v_action_items_open WHERE status='waiting' ORDER BY due_on NULLS LAST, id"),
    }


@app.post("/api/inbox/review/{item_id}")
def resolve_review(item_id: int, payload: dict = Body(...), _auth=Depends(require_auth)):
    status = (payload or {}).get("status", "resolved")
    if status not in ("resolved", "dismissed"):
        raise HTTPException(400, "status must be resolved or dismissed")
    with db.connect() as conn:
        conn.execute("UPDATE review_queue SET status=%s, resolved_at=now(), resolution=%s WHERE id=%s",
                     (status, (payload or {}).get("resolution"), item_id))
        conn.commit()
    return {"ok": True, "id": item_id, "status": status}


@app.post("/api/actions/{item_id}")
def set_action(item_id: int, payload: dict = Body(...), _auth=Depends(require_auth)):
    status = (payload or {}).get("status")
    snooze = (payload or {}).get("snooze_days")
    if status not in (None, "open", "waiting", "done", "dropped") or (status is None and not snooze):
        raise HTTPException(400, "give status (open|waiting|done|dropped) or snooze_days")
    with db.connect() as conn:
        if snooze:
            conn.execute("UPDATE action_items SET status='open', due_on=GREATEST(COALESCE(due_on, CURRENT_DATE), CURRENT_DATE) + %s WHERE id=%s",
                         (int(snooze), item_id))
        else:
            conn.execute("UPDATE action_items SET status=%s, completed_at=CASE WHEN %s='done' THEN now() ELSE completed_at END WHERE id=%s",
                         (status, status, item_id))
        conn.commit()
    return {"ok": True, "id": item_id, "status": status or "open", "snoozed": snooze}


@app.get("/api/deals/{kind}/{deal_id}/comps")
def deal_comps(kind: str, deal_id: int, radius_miles: float = 10, limit: int = 25,
               _auth=Depends(require_auth)):
    board = db.one("SELECT * FROM v_deal_board WHERE deal_kind=%s AND deal_id=%s",
                   (kind, deal_id))
    if not board:
        raise HTTPException(404, "deal not found")
    lat, lon, market = board.get("latitude"), board.get("longitude"), board.get("market")

    if lat is not None and lon is not None:
        rows = db.query(
            """SELECT id, address, city, state, units, asking_price, price_per_unit, status, sale_price, sale_price_per_unit, sale_date,
                      ROUND(haversine_miles(%s::numeric, %s::numeric, latitude, longitude), 2) AS miles
               FROM listings
               WHERE latitude IS NOT NULL AND id <> %s
                 AND merged_into_id IS NULL AND status <> 'needs_review'
                 AND COALESCE(address,'') NOT IN ('Unknown','')
                 AND haversine_miles(%s::numeric, %s::numeric, latitude, longitude) <= %s
               ORDER BY miles LIMIT %s""",
            (lat, lon, deal_id if kind == "listing" else -1, lat, lon, radius_miles, limit))
        basis = f"within {radius_miles} mi"
    else:  # no coords (e.g. package) -> same market
        rows = db.query(
            "SELECT id, address, city, state, units, asking_price, price_per_unit, status, sale_price, sale_price_per_unit, sale_date "
            "FROM listings WHERE lower(city)=lower(%s) AND id <> %s "
            "AND merged_into_id IS NULL AND status <> 'needs_review' "
            "AND COALESCE(address,'') NOT IN ('Unknown','') ORDER BY asking_price DESC LIMIT %s",
            (market, deal_id if kind == "listing" else -1, limit))
        basis = f"same market ({market})"
    return {"deal_id": deal_id, "kind": kind, "basis": basis, "count": len(rows), "comps": rows}


@app.post("/api/deals/{kind}/{deal_id}/status")
def set_deal_status(kind: str, deal_id: int, payload: dict = Body(...),
                    _auth=Depends(require_auth)):
    new_status = (payload or {}).get("status")
    reason = (payload or {}).get("reason")
    if new_status not in freshness.MANUAL_TARGETS:
        raise HTTPException(400, f"status must be one of {list(freshness.MANUAL_TARGETS)}")
    with db.connect() as conn:
        res = freshness.set_status(conn, kind, deal_id, new_status, reason)
        conn.commit()
    if not res:
        raise HTTPException(404, "deal not found")
    return res
