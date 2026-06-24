"""Single-password auth for the dashboard. One DASHBOARD_PASSWORD, a signed
HTTP-only session cookie (Starlette SessionMiddleware). No user table."""
import hmac
import os

from fastapi import HTTPException, Request


def check_password(pw: str) -> bool:
    expected = os.environ.get("DASHBOARD_PASSWORD", "")
    return bool(expected) and hmac.compare_digest(pw or "", expected)


def require_auth(request: Request):
    """Dependency: 401 unless the session cookie says authenticated."""
    if not request.session.get("authed"):
        raise HTTPException(status_code=401, detail="not authenticated")
