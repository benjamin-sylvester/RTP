"""Pipeline orchestration: a Deal Flow message -> candidate listing(s).
Routes structured senders (mlspin/primemls) through the deterministic parser and
everyone else through the AI parser; enriches missing addresses from attachment
filenames; falls back to PDF-OM text extraction when the body yields nothing.
Returns candidate dicts ready for dedup.upsert(). Does not write to the DB."""
from ingest import gmail_client as gc
from ingest import structured, attachments
from ingest.parsers import ai_extract, ai_extract_images, html_to_text

# listings.source value by parse path
_SOURCE = {"structured": "mls_export", "ai": "broker_email"}


def extract_candidates(svc, msg, session=None):
    """Return (broker_key, parse_path, [candidate, ...]) for one message."""
    bkey = gc.match_broker(msg["from_email"])
    if bkey is None:
        return None, None, []

    atts = msg.get("attachments", [])
    att_types = [(a, attachments.classify(a["filename"], a["mime"])) for a in atts]
    filename_hints = [h for h in
                      (attachments.address_from_filename(a["filename"]) for a in atts) if h]

    # 1) parse path
    if structured.can_parse(bkey):
        path = "structured"
        cands = structured.parse(bkey, msg["html"])
    else:
        path = "ai"
        body = msg["plain"].strip() or html_to_text(msg["html"])
        cands = ai_extract(body, source_label=f"{bkey} / {msg['from_email']}").get("listings", [])

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
    src = gc.broker_sources().get(bkey, {})
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
