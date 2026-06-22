"""Gmail client for the Deal Flow pipeline.
Auth from .env refresh token; list/fetch threads under a label; decode bodies and
attachments; map a sender address to a broker_format_config source key.
Read + label scope (gmail.modify); never sends or deletes."""
import base64
import os
import pathlib
import re

import yaml
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def _load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def service():
    _load_env()
    creds = Credentials(
        None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        token_uri=TOKEN_URI,
        scopes=SCOPES,
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def label_id(svc, name):
    for l in svc.users().labels().list(userId="me").execute().get("labels", []):
        if l["name"] == name:
            return l["id"]
    return None


def ensure_label(svc, name):
    """Return the id of label `name`, creating it (nested ok, e.g. 'RTP/Ingested')."""
    lid = label_id(svc, name)
    if lid:
        return lid
    created = svc.users().labels().create(
        userId="me",
        body={"name": name, "labelListVisibility": "labelShow",
              "messageListVisibility": "show"},
    ).execute()
    return created["id"]


def list_message_ids(svc, label_name, after=None, max_results=None):
    """List message ids under a label. `after` = 'YYYY/MM/DD' Gmail date filter."""
    lid = label_id(svc, label_name)
    if not lid:
        raise RuntimeError(f"Label '{label_name}' not found")
    q = f"after:{after}" if after else None
    out, page = [], None
    while True:
        resp = svc.users().messages().list(
            userId="me", labelIds=[lid], q=q, pageToken=page,
            maxResults=min(500, max_results or 500),
        ).execute()
        out.extend(m["id"] for m in resp.get("messages", []))
        page = resp.get("nextPageToken")
        if not page or (max_results and len(out) >= max_results):
            break
    return out[:max_results] if max_results else out


def _walk_parts(part, acc):
    """Collect (mime, part) leaves; recurse multiparts."""
    if part.get("parts"):
        for p in part["parts"]:
            _walk_parts(p, acc)
    else:
        acc.append(part)


def _decode(data):
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", "replace")


def get_message(svc, msg_id):
    """Return a normalized message dict: headers, plain/html body, attachment descriptors."""
    msg = svc.users().messages().get(userId="me", id=msg_id, format="full").execute()
    payload = msg.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

    leaves = []
    _walk_parts(payload, leaves)
    plain, html, attachments = [], [], []
    for p in leaves:
        mime = p.get("mimeType", "")
        body = p.get("body", {})
        filename = p.get("filename") or ""
        if filename and (body.get("attachmentId") or body.get("data")):
            attachments.append({
                "filename": filename, "mime": mime,
                "size": body.get("size", 0),
                "attachment_id": body.get("attachmentId"),
            })
        elif mime == "text/plain" and body.get("data"):
            plain.append(_decode(body["data"]))
        elif mime == "text/html" and body.get("data"):
            html.append(_decode(body["data"]))

    from_raw = headers.get("from", "")
    m = re.search(r"<([^>]+)>", from_raw)
    from_email = (m.group(1) if m else from_raw).strip().lower()
    return {
        "id": msg_id,
        "thread_id": msg.get("threadId"),
        "from_raw": from_raw,
        "from_email": from_email,
        "subject": headers.get("subject", ""),
        "date": headers.get("date", ""),
        "internal_date_ms": int(msg.get("internalDate", 0)),
        "snippet": msg.get("snippet", ""),
        "plain": "\n".join(plain),
        "html": "\n".join(html),
        "attachments": attachments,
        "label_ids": msg.get("labelIds", []),
    }


def download_attachment(svc, msg_id, attachment_id):
    """Return raw bytes for an attachment."""
    att = svc.users().messages().attachments().get(
        userId="me", messageId=msg_id, id=attachment_id).execute()
    return base64.urlsafe_b64decode(att["data"].encode())


_SOURCES = None


def broker_sources():
    global _SOURCES
    if _SOURCES is None:
        cfg = yaml.safe_load((ROOT / "config" / "broker_format_config.yaml").read_text())
        _SOURCES = cfg["sources"]
    return _SOURCES


def match_broker(from_email):
    """Map a sender address to a broker_format_config key, or None.
    Exact `from` match first, then `domains` fallback (e.g. any @northeastpcg.com)."""
    fe = (from_email or "").lower().strip()
    if not fe:
        return None
    sources = broker_sources()
    for key, s in sources.items():
        if fe in [a.lower() for a in s.get("from", [])]:
            return key
    domain = fe.split("@")[-1]
    for key, s in sources.items():
        if domain in [d.lower() for d in s.get("domains", [])]:
            return key
    return None
