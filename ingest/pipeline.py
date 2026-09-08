"""Pipeline orchestration: a Deal Flow message -> candidate listing(s).
Routes structured senders (mlspin/primemls) through the deterministic parser and
everyone else through the AI parser; enriches missing addresses from attachment
filenames; falls back to PDF-OM text extraction when the body yields nothing.
Returns candidate dicts ready for dedup.upsert(). Does not write to the DB."""
import re

from ingest import gmail_client as gc
from ingest import structured, attachments
from ingest.parsers import ai_extract, ai_extract_images, html_to_text

# listings.source value by parse path
_SOURCE = {"structured": "mls_export", "ai": "broker_email"}

# --- scan-all deal detector -------------------------------------------------
# For inboxes scanned wholesale (unknown senders included), a cheap keyword gate
# decides whether a message is worth a Claude parse. Avoids AI-parsing every
# newsletter/receipt and keeps false-positive listings down.
_PRICE = re.compile(r"\$\s?\d{2,}(?:[\d,]*)(?:\.\d+)?\s?(k|m|mm)?\b", re.I)
_ADDR = re.compile(
    r"\b\d{1,6}\s+[A-Za-z0-9.\-' ]{2,40}\s"
    r"(st|street|ave|avenue|rd|road|dr|drive|ln|lane|blvd|ct|court|pl|place|"
    r"way|ter|terrace|hwy|highway|cir|circle)\b", re.I)
_DEAL_KW = re.compile(
    r"\b(multi[- ]?family|duplex|triplex|four[- ]?plex|apartment|units?|unit mix|"
    r"cap rate|\bnoi\b|rent roll|t-?12|for sale|listing|price per unit|gross rent|"
    r"pro[- ]?forma|offering memorandum|\bom\b|\bmls\b|bed(?:room)?s?|sq\.?\s?ft)\b", re.I)
# any one of these is strong enough on its own
_STRONG = re.compile(
    r"\b(multi[- ]?family|cap rate|rent roll|offering memorandum|price per unit|"
    r"\bt-?12\b|pro[- ]?forma)\b", re.I)
# never re-ingest the system's own briefing (it is full of addresses/prices)
_BRIEFING = re.compile(r"RTP Deal Briefing", re.I)


def looks_like_deal(subject, body):
    """Cheap pre-filter for scan-all inboxes: True if the message plausibly
    describes a real-estate deal. Requires 2 of {price, address, deal-keyword},
    or one strong signal."""
    text = f"{subject}\n{body}"[:8000]
    if _STRONG.search(text):
        return True
    signals = sum(bool(rx.search(text)) for rx in (_PRICE, _ADDR, _DEAL_KW))
    return signals >= 2


def extract_candidates(svc, msg, session=None, allow_unknown=False):
    """Return (broker_key, parse_path, [candidate, ...]) for one message.

    allow_unknown=True (scan-all inboxes): mail from senders NOT in the broker
    config is still parsed, gated by looks_like_deal() so only plausible deals
    reach the Claude parser. Known-broker behavior is unchanged."""
    bkey = gc.match_broker(msg["from_email"])
    if bkey is None and not allow_unknown:
        return None, None, []

    # scan-all guard: never re-ingest the system's own daily briefing
    if bkey is None and _BRIEFING.search(msg.get("subject", "")):
        return None, "skip_briefing", []

    atts = msg.get("attachments", [])
    att_types = [(a, attachments.classify(a["filename"], a["mime"])) for a in atts]
    filename_hints = [h for h in
                      (attachments.address_from_filename(a["filename"]) for a in atts) if h]

    # 1) parse path
    if bkey is not None and structured.can_parse(bkey):
        path = "structured"
        cands = structured.parse(bkey, msg["html"])
    else:
        body = msg["plain"].strip() or html_to_text(msg["html"])
        if bkey is None:
            # unknown sender in a scan-all inbox: gate before spending a Claude call
            if not looks_like_deal(msg.get("subject", ""), body):
                return None, "skip_nondeal", []
            path = "ai_scan"
            label = f"scan / {msg['from_email']}"
        else:
            path = "ai"
            label = f"{bkey} / {msg['from_email']}"
        cands = ai_extract(body, source_label=label).get("listings", [])

    # 2) PDF-OM fallback: no body listings but an OM pdf is attached.
    #    Try text extraction; if the PDF is image-based (no text), render pages
    #    to images and use Claude vision.
    if not cands:
        for a, kind in att_types:
            if kind in ("om_pdf", "rent_roll", "t12") and a.get("attachment_id"):
                data = gc.download_attachment(svc, msg["id"], a["attachment_id"])
                text = attachments.pdf_text(data)
                if text:
                    cands = ai_extract(text, source_label=f"{bkey} OM / {a['filename']}").get("listings", [])
                    path = "ai_pdf"
                # vision fallback when there is no text OR the text yielded nothing
                # (image-based riders, or text that is just disclosure boilerplate)
                if not cands:
                    images = attachments.pdf_to_images(data)
                    if images:
                        cands = ai_extract_images(
                            images, source_label=f"{bkey} OM / {a['filename']}").get("listings", [])
                        path = "ai_pdf_vision"
                if cands:
                    break

    # 3) enrich a single addressless listing from a single filename hint
    if len(cands) == 1 and filename_hints:
        c = cands[0]
        if not c.get("address"):
            c["address"] = filename_hints[0]["address"]
            if not c.get("city") and filename_hints[0].get("city"):
                c["city"] = filename_hints[0]["city"]

    # 4) sender defaults + provenance
    src = gc.broker_sources().get(bkey, {}) if bkey else {}
    froms = src.get("from", [])
    for c in cands:
        c.setdefault("broker_email", froms[0] if froms else msg["from_email"])
        c["_thread_id"] = msg["thread_id"]
        c["_broker_key"] = bkey
        c["_attachments"] = [f"{a['filename']}::{k}" for a, k in att_types]
        c["_filename_hints"] = [h["address"] for h in filename_hints]
    return bkey, path, cands


def source_for(path):
    return _SOURCE.get("structured" if path == "structured" else "ai", "broker_email")
