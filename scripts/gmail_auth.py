"""Phase 1 — one-time Gmail OAuth: mint a refresh token and write it to .env.

Prereqs (Google Cloud Console, done by Ben):
  1. Enable the Gmail API on a project.
  2. OAuth consent screen: External, add ben.sylvester18@gmail.com as a test user.
  3. Create an OAuth client ID of type "Desktop app".
  4. Download its JSON and save it in the project root as `client_secret.json`.

Then run:  .venv/Scripts/python.exe scripts/gmail_auth.py
A browser opens for consent; on success this writes GMAIL_CLIENT_ID,
GMAIL_CLIENT_SECRET, and GMAIL_REFRESH_TOKEN into .env (other keys preserved).

Scope: gmail.modify (read messages/attachments + add the 'processed' label;
does NOT allow sending or permanent deletion).
"""
import json
import pathlib
import re
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECRET = ROOT / "client_secret.json"
ENV = ROOT / ".env"
SCOPES = ["https://www.googleapis.com/auth/gmail.modify",
          "https://www.googleapis.com/auth/gmail.send"]


def upsert_env(updates: dict):
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    keys = set(updates)
    out, seen = [], set()
    for line in lines:
        m = re.match(r"\s*([A-Z0-9_]+)\s*=", line)
        if m and m.group(1) in keys:
            k = m.group(1)
            out.append(f"{k}={updates[k]}")
            seen.add(k)
        else:
            out.append(line)
    for k, v in updates.items():
        if k not in seen:
            out.append(f"{k}={v}")
    ENV.write_text("\n".join(out) + "\n")


def main():
    if not SECRET.exists():
        sys.exit(f"Missing {SECRET}. Download the Desktop OAuth client JSON from "
                 f"Google Cloud Console and save it there first.")
    info = json.loads(SECRET.read_text())
    conf = info.get("installed") or info.get("web")
    if not conf:
        sys.exit("client_secret.json is not a Desktop/Installed OAuth client.")

    flow = InstalledAppFlow.from_client_secrets_file(str(SECRET), SCOPES)
    print("Opening browser for Google consent (sign in as ben.sylvester18@gmail.com)...")
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    if not creds.refresh_token:
        sys.exit("No refresh token returned. Revoke prior access at "
                 "https://myaccount.google.com/permissions and re-run with prompt=consent.")

    upsert_env({
        "GMAIL_CLIENT_ID": conf["client_id"],
        "GMAIL_CLIENT_SECRET": conf["client_secret"],
        "GMAIL_REFRESH_TOKEN": creds.refresh_token,
    })
    print("\nSUCCESS. Wrote GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN to .env")
    print(f"Token grants scope: {SCOPES[0]}")


if __name__ == "__main__":
    main()
