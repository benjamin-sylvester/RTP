"""Structured parser for the two MLS notification-email layouts (parse:html).
These are formatted HTML cards (not labeled exports), so we anchor on the MLS#
and pull the regular fields with regex. Deterministic and free; the AI parser is
the fallback for free-form senders. Returns the same listing dicts as ai_extract,
money in DOLLARS. Multi-listing digests -> multiple dicts.
"""
import re

from ingest.parsers import html_to_text

_MONEY = r"\$\s*([\d,]+)"
# "45 Laurel St, Leominster, MA" (single-line, MLS-PIN style). Intra-street spacing
# is [ \t] only so the match cannot bleed across the preceding price line's newline.
_ADDR_INLINE = re.compile(
    r"(\d+[\w\-]*[ \t]+[^,\n]+?),\s*([A-Za-z .'-]+?),\s*([A-Z]{2})(?:\s+(\d{5}))?")
# "Manchester, NH 03102" (city/state/zip on its own line, PrimeMLS style)
_CITY_LINE = re.compile(r"^([A-Za-z .'-]+?),\s*([A-Z]{2})\s+(\d{5})", re.M)


def _num(s):
    return int(s.replace(",", "")) if s else None


def parse_mlspin(text):
    """Cards read: $price / 'street, city, ST' / 'N Units' / 'MLS#: number'."""
    out = []
    anchors = list(re.finditer(r"MLS#:\s*\n?\s*(\d+)", text))
    prev = 0
    for a in anchors:
        seg = text[prev:a.start()]
        prev = a.end()
        addr = _ADDR_INLINE.search(seg)
        price = re.findall(_MONEY, seg)
        units = re.search(r"(\d+)\s+Units?", seg)
        sf = re.search(r"([\d,]+)\s+Living Area", seg)
        if not (addr or price):
            continue
        out.append({
            "address": addr.group(1).strip() if addr else None,
            "city": addr.group(2).strip() if addr else None,
            "state": addr.group(3) if addr else None,
            "zip": addr.group(4) if (addr and addr.group(4)) else None,
            "units": _num(units.group(1)) if units else None,
            "asking_price": _num(price[-1]) if price else None,
            "building_sf": _num(sf.group(1)) if sf else None,
            "external_id": a.group(1),
            "year_built": None, "lot_sf": None, "unit_mix": [],
            "gross_revenue": None, "total_expenses": None, "noi": None,
            "vacancy_rate": None, "broker_name": None, "broker_email": None,
            "listing_date": None,
        })
    return out


def parse_primemls(text):
    """Cards: 'street' / 'City, ST ZIP' / 'MLS # number' / '$price' /
    'Total Units: N' / 'Days on Market: N' / 'Above Grade Finished Area: N'."""
    out = []
    anchors = list(re.finditer(r"MLS\s*#\s*\n?\s*(\d+)", text))
    for i, a in enumerate(anchors):
        before = text[max(0, a.start() - 300):a.start()]
        after_end = anchors[i + 1].start() if i + 1 < len(anchors) else len(text)
        after = text[a.end():after_end]
        cl = list(_CITY_LINE.finditer(before))
        city = state = zipc = address = None
        if cl:
            last = cl[-1]
            city, state, zipc = last.group(1).strip(), last.group(2), last.group(3)
            pre_lines = [l.strip() for l in before[:last.start()].splitlines() if l.strip()]
            address = pre_lines[-1] if pre_lines else None
        price = re.findall(_MONEY, after)
        units = re.search(r"Total Units:\s*\n?\s*(\d+)", after)
        dom = re.search(r"Days on Market:\s*\n?\s*(\d+)", after)
        sf = re.search(r"Finished Area:\s*\n?\s*([\d,]+)", after)
        out.append({
            "address": address, "city": city, "state": state, "zip": zipc,
            "units": _num(units.group(1)) if units else None,
            "asking_price": _num(price[0]) if price else None,
            "building_sf": _num(sf.group(1)) if sf else None,
            "external_id": a.group(1),
            "days_on_market": _num(dom.group(1)) if dom else None,
            "year_built": None, "lot_sf": None, "unit_mix": [],
            "gross_revenue": None, "total_expenses": None, "noi": None,
            "vacancy_rate": None, "broker_name": None, "broker_email": None,
            "listing_date": None,
        })
    return out


_DISPATCH = {"mlspin": parse_mlspin, "primemls": parse_primemls}


def can_parse(broker_key):
    return broker_key in _DISPATCH


def parse(broker_key, html):
    """Structured parse for mlspin/primemls; returns list of listing dicts."""
    text = html_to_text(html)
    return _DISPATCH[broker_key](text)
