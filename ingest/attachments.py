"""Attachment handling for the pipeline.
- address_from_filename: off-market addresses often live ONLY in the attachment
  filename (e.g. '9 Carroll St.pdf', 'FRPM_49_Nelson_St_New_Bedford_Flipbook.html').
- pdf_text: extract text from a PDF OM (PyMuPDF) to feed the AI parser.
- classify: MLS export / OM(pdf) / rent_roll / t12 / flipbook(html) / spreadsheet.
"""
import io
import re

import fitz  # PyMuPDF

_STREET = (r"\b(\d{1,6}(?:-\d{1,6})?)\s+([A-Za-z0-9 ]+?)\s+"
           r"(St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Blvd|Way|Ct|Court|Pl|Place|Hwy|Highway|Ter|Terrace)\b")
_CITY_HINT = re.compile(
    r"(New Bedford|Fall River|Manchester|Nashua|Dover|Rochester|Worcester|Lynn|"
    r"Leominster|Waltham|Providence|Pittsfield|Allenstown|Hampton|Somersworth|"
    r"Derry|Londonderry|Salem|Farmington|Milton)", re.I)


def address_from_filename(filename):
    """Best-effort {address, city} from an attachment filename. None if nothing found."""
    if not filename:
        return None
    base = re.sub(r"\.[A-Za-z0-9]+$", "", filename)            # drop extension
    cleaned = re.sub(r"[_]+", " ", base)                        # underscores -> spaces
    cleaned = re.sub(r"\b(LITE|Flipbook|Flyer|OM|Final|v\d+|copy)\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    m = re.search(_STREET, cleaned, re.I)
    if not m:
        return None
    address = f"{m.group(1)} {m.group(2).strip()} {m.group(3)}"
    address = re.sub(r"\s{2,}", " ", address).strip()
    city = None
    cm = _CITY_HINT.search(cleaned)
    if cm:
        city = cm.group(1).title()
    return {"address": address, "city": city}


def pdf_text(data, max_pages=6):
    try:
        doc = fitz.open(stream=io.BytesIO(data), filetype="pdf")
    except Exception:
        return ""
    parts = []
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        parts.append(page.get_text())
    return "\n".join(parts).strip()


def pdf_to_images(data, max_pages=5, dpi=150):
    """Render PDF pages to PNG bytes (for image-based OMs/riders that have no text)."""
    try:
        doc = fitz.open(stream=io.BytesIO(data), filetype="pdf")
    except Exception:
        return []
    out = []
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        pix = page.get_pixmap(dpi=dpi)
        out.append(pix.tobytes("png"))
    return out


def classify(filename, mime):
    fn = (filename or "").lower()
    if mime == "application/pdf" or fn.endswith(".pdf"):
        if re.search(r"rent.?roll", fn):
            return "rent_roll"
        if re.search(r"t-?12|trailing|income|expense|p&l|operating", fn):
            return "t12"
        return "om_pdf"
    if "spreadsheet" in (mime or "") or fn.endswith((".xlsx", ".xls", ".csv")):
        if re.search(r"rent.?roll", fn):
            return "rent_roll"
        if re.search(r"expense|income|t-?12|operating|p&l", fn):
            return "t12"
        return "mls_export"
    if fn.endswith((".html", ".htm")) or "html" in (mime or ""):
        return "flipbook"
    return "other"
