"""Public intake for rtprei.com: investor-interest form and newsletter signup.
Not behind the dashboard login. Instead every call must carry the shared secret in the
X-Intake-Secret header (INTAKE_SECRET), which only the Cloudflare Pages Function on rtprei.com
knows. If INTAKE_SECRET is unset the endpoints are off. Responses never say whether an email
already exists."""
import hmac
import os
import re

from fastapi import APIRouter, Body, Header, HTTPException

from api import db

router = APIRouter(prefix="/api/public")

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
ABOUT = {
    "current_investor": "existing RTP investor",
    "exploring": "individual investor exploring",
    "family_office": "family office or fund",
    "other": "other",
}
RANGE = {
    "not_sure": "not sure yet",
    "under_25k": "under $25,000",
    "25_50k": "$25,000 to $50,000",
    "50_100k": "$50,000 to $100,000",
    "100_250k": "$100,000 to $250,000",
    "250k_plus": "$250,000 or more",
}
HEARD = {
    "linkedin": "LinkedIn",
    "referral": "a friend or colleague",
    "event": "an event",
    "search": "web search",
    "other": "other",
}


def _check_secret(supplied: str | None):
    expected = os.environ.get("INTAKE_SECRET", "")
    if not expected:
        raise HTTPException(503, "intake is off")
    if not hmac.compare_digest(supplied or "", expected):
        raise HTTPException(401, "bad secret")


def _clean(v, n):
    return _CTRL.sub("", (v or "")).strip()[:n]


def _email(v):
    e = _clean(v, 320).lower()
    if not _EMAIL.match(e):
        raise HTTPException(400, "valid email required")
    return e


def _ben_id(conn):
    r = conn.execute("SELECT id FROM people WHERE full_name='Ben Sylvester' ORDER BY id LIMIT 1").fetchone()
    return r["id"] if r else None


def _person_by_email(conn, email):
    r = conn.execute(
        "SELECT COALESCE(p.merged_into_id, p.id) AS id FROM people_emails e "
        "JOIN people p ON p.id = e.person_id WHERE e.email = %s LIMIT 1", (email,)).fetchone()
    return r["id"] if r else None


@router.post("/newsletter")
def newsletter(payload: dict = Body(...), x_intake_secret: str | None = Header(None)):
    _check_secret(x_intake_secret)
    if _clean(payload.get("website"), 50):  # honeypot: bots fill it
        return {"ok": True}
    email = _email(payload.get("email"))
    with db.connect() as conn:
        person_id = _person_by_email(conn, email)
        conn.execute(
            "INSERT INTO newsletter_subscribers (email, person_id, source, consent_text) "
            "VALUES (%s, %s, 'website', %s) "
            "ON CONFLICT (email) DO UPDATE SET unsubscribed_at = NULL, "
            "person_id = COALESCE(newsletter_subscribers.person_id, EXCLUDED.person_id)",
            (email, person_id, _clean(payload.get("consent_text"), 300) or None))
        conn.commit()
    return {"ok": True}


@router.post("/investor")
def investor(payload: dict = Body(...), x_intake_secret: str | None = Header(None)):
    _check_secret(x_intake_secret)
    if _clean(payload.get("website"), 50):
        return {"ok": True}
    first = _clean(payload.get("first_name"), 80)
    last = _clean(payload.get("last_name"), 80)
    if not first or not last:
        raise HTTPException(400, "first and last name required")
    email = _email(payload.get("email"))
    phone = _clean(payload.get("phone"), 40) or None
    about = ABOUT.get(_clean(payload.get("about"), 30), "not stated")
    check = RANGE.get(_clean(payload.get("range"), 20), "not stated")
    heard = HEARD.get(_clean(payload.get("heard"), 20), "not stated")
    message = _clean(payload.get("message"), 2000)
    full = f"{first} {last}"

    with db.connect() as conn:
        ben = _ben_id(conn)
        pid = _person_by_email(conn, email)
        if pid is None:
            pid = conn.execute(
                "INSERT INTO people (full_name, first_name, last_name, roles, phone, source, notes) "
                "VALUES (%s, %s, %s, ARRAY['lp_prospect'], %s, 'website', %s) RETURNING id",
                (full, first, last, phone, "Came in through the rtprei.com investor form. Not yet tiered.")).fetchone()["id"]
            conn.execute("INSERT INTO people_emails (person_id, email, is_primary) VALUES (%s, %s, true)", (pid, email))
        else:
            # known person: keep their roles and tier, fill a missing phone, add lp_prospect only if
            # they are not already an lp / lp_prospect / capital_partner
            conn.execute(
                "UPDATE people SET phone = COALESCE(phone, %s), "
                "roles = CASE WHEN roles && ARRAY['lp','lp_prospect','capital_partner']::text[] THEN roles "
                "ELSE array_append(roles, 'lp_prospect') END, updated_at = now() WHERE id = %s",
                (phone, pid))

        summary = f"Website investor form. Describes self as: {about}. Check size range: {check}. Heard about us via: {heard}."
        if message:
            summary += f" Note: {message}"
        conn.execute(
            "INSERT INTO interactions (person_id, channel, direction, occurred_at, summary, by_person_id, source, source_id) "
            "VALUES (%s, 'other', 'inbound', now(), %s, %s, 'website_investor', %s)",
            (pid, summary[:2500], ben, f"web-{pid}-{os.urandom(4).hex()}"))

        open_item = conn.execute(
            "SELECT 1 FROM action_items WHERE person_id=%s AND source='website_investor' "
            "AND status IN ('open','waiting')", (pid,)).fetchone()
        if not open_item:
            conn.execute(
                "INSERT INTO action_items (person_id, category, title, details, due_on, status, owner_person_id, source) "
                "VALUES (%s, 'capital', %s, %s, now()::date + 1, 'open', %s, 'website_investor')",
                (pid, f"Reply to {full} (website investor form)",
                 f"Email: {email}. " + (f"Phone: {phone}. " if phone else "") + f"About: {about}. Range: {check}. Heard via: {heard}. "
                 + (f"Note: {message[:400]}" if message else ""), ben))

        # newsletter only if they ticked the box
        if payload.get("newsletter"):
            conn.execute(
                "INSERT INTO newsletter_subscribers (email, person_id, source, consent_text) "
                "VALUES (%s, %s, 'website_investor', 'Ticked newsletter box on investor form') "
                "ON CONFLICT (email) DO UPDATE SET unsubscribed_at = NULL, "
                "person_id = COALESCE(newsletter_subscribers.person_id, EXCLUDED.person_id)", (email, pid))
        conn.commit()
    return {"ok": True}
