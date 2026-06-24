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

ACTIVE = ["lead", "underwriting", "under_contract"]
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
    comps: bool = False, stale: bool = False, needs_review: bool = False,
    sort: str = "default", order: str = "desc",
    limit: int = 200, offset: int = 0,
    _auth=Depends(require_auth),
):
    # status set: explicit param wins; else active + requested toggles
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
    else:
        statuses = list(ACTIVE)
        if comps:
            statuses.append("comp_only")
        if stale:
            statuses.append("stale")
        if needs_review:
            statuses.append("needs_review")

    where = ["status = ANY(%s)"]
    params: list = [statuses]
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
    return detail


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
            """SELECT id, address, city, state, units, asking_price, price_per_unit, status,
                      ROUND(haversine_miles(%s::numeric, %s::numeric, latitude, longitude), 2) AS miles
               FROM listings
               WHERE latitude IS NOT NULL AND id <> %s
                 AND haversine_miles(%s::numeric, %s::numeric, latitude, longitude) <= %s
               ORDER BY miles LIMIT %s""",
            (lat, lon, deal_id if kind == "listing" else -1, lat, lon, radius_miles, limit))
        basis = f"within {radius_miles} mi"
    else:  # no coords (e.g. package) -> same market
        rows = db.query(
            "SELECT id, address, city, state, units, asking_price, price_per_unit, status "
            "FROM listings WHERE lower(city)=lower(%s) AND id <> %s ORDER BY asking_price DESC LIMIT %s",
            (market, deal_id if kind == "listing" else -1, limit))
        basis = f"same market ({market})"
    return {"deal_id": deal_id, "kind": kind, "basis": basis, "count": len(rows), "comps": rows}
