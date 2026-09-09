"""Gmail OAuth token mint that avoids `requests`.

Why this exists: on this machine something on the network path (AV / firewall
doing TLS inspection) drops `requests`/`urllib3` connections to
oauth2.googleapis.com — proven by scripts/_tls_probe.py, where raw ssl and
httpx succeed but requests fails with SSL EOF. The stock scripts/gmail_auth.py
uses requests via google-auth-oauthlib, so it can't finish the token exchange.

This does the same job with only the standard library + httpx:
  1. loopback HTTP server catches Google's redirect (browser part is unaffected)
  2. PKCE S256, same scopes (gmail.modify + gmail.send)
  3. code -> token exchanged with a direct httpx POST
  4. refresh token written to .env (other keys preserved)

    .venv\\Scripts\\python.exe scripts\\gmail_auth_httpx.py
        -> mints the PRIMARY inbox: writes GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN

    .venv\\Scripts\\python.exe scripts\\gmail_auth_httpx.py GMAIL_REFRESH_TOKEN_RTP
        -> mints a SECONDARY inbox (sign in as that account in the browser):
           writes only GMAIL_REFRESH_TOKEN_RTP, leaving the primary token intact.
           The OAuth client (id/secret) is shared across inboxes.
"""
import base64
import hashlib
import http.server
import json
import pathlib
import re
import secrets
import sys
import threading
import urllib.parse
import webbrowser

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECRET = ROOT / "client_secret.json"
ENV = ROOT / ".env"
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = ["https://www.googleapis.com/auth/gmail.modify",
          "https://www.googleapis.com/auth/gmail.send",
          "https://www.googleapis.com/auth/drive.readonly"]


def upsert_env(updates):
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    keys, out, seen = set(updates), [], set()
    for line in lines:
        m = re.match(r"\s*([A-Z0-9_]+)\s*=", line)
        if m and m.group(1) in keys:
            out.append(f"{m.group(1)}={updates[m.group(1)]}")
            seen.add(m.group(1))
        else:
            out.append(line)
    for k, v in updates.items():
        if k not in seen:
            out.append(f"{k}={v}")
    ENV.write_text("\n".join(out) + "\n")


class _Catcher(http.server.BaseHTTPRequestHandler):
    result = {}

    def do_GET(self):
        q = urllib.parse.urlparse(self.path).query
        _Catcher.result = dict(urllib.parse.parse_qsl(q))
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        ok = "code" in _Catcher.result
        self.wfile.write(
            b"<h2>Authorization received. You can close this tab.</h2>" if ok
            else b"<h2>Authorization failed. Check the terminal.</h2>")

    def log_message(self, *a):
        pass


def main():
    if not SECRET.exists():
        sys.exit(f"Missing {SECRET}")
    info = json.loads(SECRET.read_text())
    conf = info.get("installed") or info.get("web")
    if not conf:
        sys.exit("client_secret.json is not a Desktop/Installed OAuth client.")
    client_id, client_secret = conf["client_id"], conf["client_secret"]

    # loopback server on an ephemeral port (desktop clients allow any localhost port)
    server = http.server.HTTPServer(("127.0.0.1", 0), _Catcher)
    port = server.server_address[1]
    redirect_uri = f"http://localhost:{port}/"

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)

    auth_url = AUTH_URI + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    })

    print("Opening browser for Google consent (sign in as ben.sylvester18@gmail.com)...")
    print("If it doesn't open, paste this URL:\n" + auth_url + "\n")
    threading.Thread(target=lambda: webbrowser.open(auth_url), daemon=True).start()

    server.handle_request()   # blocks until the redirect hits
    res = _Catcher.result
    if res.get("state") != state:
        sys.exit("State mismatch — aborting.")
    if "code" not in res:
        sys.exit(f"No code returned: {res}")

    print("Code received. Exchanging for token via httpx...")
    r = httpx.post(TOKEN_URI, data={
        "grant_type": "authorization_code",
        "code": res["code"],
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }, timeout=30)
    if r.status_code != 200:
        sys.exit(f"Token exchange failed ({r.status_code}): {r.text[:300]}")
    tok = r.json()
    if not tok.get("refresh_token"):
        sys.exit("No refresh_token returned. Revoke prior access at "
                 "https://myaccount.google.com/permissions and re-run.")

    target = sys.argv[1] if len(sys.argv) > 1 else "GMAIL_REFRESH_TOKEN"
    if not re.fullmatch(r"GMAIL_REFRESH_TOKEN(_[A-Z0-9]+)?", target):
        sys.exit(f"Invalid target var '{target}'. Use GMAIL_REFRESH_TOKEN or "
                 f"GMAIL_REFRESH_TOKEN_<KEY> (e.g. GMAIL_REFRESH_TOKEN_RTP).")
    if target == "GMAIL_REFRESH_TOKEN":
        # primary inbox: also (re)write the shared OAuth client id/secret
        upsert_env({
            "GMAIL_CLIENT_ID": client_id,
            "GMAIL_CLIENT_SECRET": client_secret,
            "GMAIL_REFRESH_TOKEN": tok["refresh_token"],
        })
        print("\nSUCCESS. Wrote GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, "
              "GMAIL_REFRESH_TOKEN to .env")
    else:
        # secondary inbox: only its refresh token; client id/secret are shared
        upsert_env({target: tok["refresh_token"]})
        print(f"\nSUCCESS. Wrote {target} to .env (primary token untouched).")
    print("Scopes:", tok.get("scope", " ".join(SCOPES)))


if __name__ == "__main__":
    main()
