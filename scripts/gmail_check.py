"""Phase 1 — sanity check Gmail connectivity using the refresh token in .env.
Builds a service, confirms the 'Deal Flow' label exists, and counts its threads.
Read-only; does not modify anything."""
import os
import sys

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from _conn import load_env

TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def service():
    load_env()
    for k in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"):
        if not os.environ.get(k):
            sys.exit(f"{k} not set in .env — run scripts/gmail_auth.py first.")
    creds = Credentials(
        None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        token_uri=TOKEN_URI,
        scopes=SCOPES,
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def main():
    svc = service()
    profile = svc.users().getProfile(userId="me").execute()
    print(f"Authenticated as: {profile['emailAddress']} "
          f"({profile['messagesTotal']} messages total)\n")

    label_name = os.environ.get("GMAIL_DEAL_FLOW_LABEL", "Deal Flow")
    labels = svc.users().labels().list(userId="me").execute().get("labels", [])
    match = next((l for l in labels if l["name"] == label_name), None)
    if not match:
        print(f"Label '{label_name}' NOT found. Available labels:")
        for l in sorted(l["name"] for l in labels):
            print(f"  - {l}")
        sys.exit(1)

    full = svc.users().labels().get(userId="me", id=match["id"]).execute()
    print(f"Label '{label_name}' found (id={match['id']}): "
          f"{full.get('threadsTotal', '?')} threads, "
          f"{full.get('messagesTotal', '?')} messages.")
    msgs = svc.users().messages().list(
        userId="me", labelIds=[match["id"]], maxResults=5).execute()
    print(f"Sample of recent message ids under the label: "
          f"{[m['id'] for m in msgs.get('messages', [])]}")
    print("\nGmail connectivity OK — ready to build ingestion.")


if __name__ == "__main__":
    main()
