"""Google Drive read client for the UW-model sync (shared-drive aware).

Lets the cloud cron fetch models from Drive without a local mount. Uses the same
OAuth credentials as Gmail; the token must additionally carry the drive.readonly
scope (re-mint with scripts/gmail_auth_httpx.py after adding it to SCOPES).

All calls pass supportsAllDrives / includeItemsFromAllDrives because the models
live on the "RTP G-Drive" shared drive, not My Drive.
"""
import io
import os
import re

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from ingest.gmail_client import _load_env, TOKEN_URI

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FOLDER_MIME = "application/vnd.google-apps.folder"


def service():
    """Drive client, authed as the account that owns the RTP shared drive.
    The 'RTP G-Drive' lives on the ben@rtprei.com Workspace account, so prefer
    that token: DRIVE_REFRESH_TOKEN, else the RTP inbox token, else personal."""
    _load_env()
    tok = (os.environ.get("DRIVE_REFRESH_TOKEN")
           or os.environ.get("GMAIL_REFRESH_TOKEN_RTP")
           or os.environ["GMAIL_REFRESH_TOKEN"])
    creds = Credentials(
        None,
        refresh_token=tok,
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        token_uri=TOKEN_URI,
        scopes=[DRIVE_SCOPE],
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _list(svc, q, fields="files(id,name,modifiedTime,mimeType)"):
    return svc.files().list(
        q=q, fields=f"files(id,name,modifiedTime,mimeType),nextPageToken",
        supportsAllDrives=True, includeItemsFromAllDrives=True,
        pageSize=200).execute().get("files", [])


def find_subfolder(svc, parent_id, name):
    safe = name.replace("'", "\\'")
    q = (f"'{parent_id}' in parents and mimeType='{FOLDER_MIME}' "
         f"and name='{safe}' and trashed=false")
    fs = _list(svc, q)
    return fs[0]["id"] if fs else None


def latest_model(svc, folder_id, analysis_sub="4.0 Investment Analysis"):
    """Newest UW workbook in <deal folder>/4.0 Investment Analysis. Prefers the
    highest _vNN, falls back to most-recently-modified. Returns a dict or None."""
    sub = find_subfolder(svc, folder_id, analysis_sub) or folder_id
    q = f"'{sub}' in parents and mimeType='{XLSX_MIME}' and trashed=false"
    files = [f for f in _list(svc, q) if not f["name"].startswith("~$")]
    if not files:
        return None

    def ver(f):
        m = re.search(r"[_ ]v(\d+)\.xlsx$", f["name"], re.I)
        return int(m.group(1)) if m else -1
    files.sort(key=lambda f: (ver(f), f["modifiedTime"]))
    best = files[-1]
    m = re.search(r"[_ ]v(\d+)\.xlsx$", best["name"], re.I)
    return {"id": best["id"], "filename": best["name"],
            "version": (f"v{m.group(1)}" if m else None),
            "modifiedTime": best["modifiedTime"]}


def download(svc, file_id):
    """Return a BytesIO of the file's content (openpyxl can load it directly)."""
    req = svc.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req, chunksize=5 * 1024 * 1024)
    done = False
    while not done:
        _, done = dl.next_chunk()
    buf.seek(0)
    return buf
