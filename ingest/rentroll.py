"""Phase 3 step 1 — rent-roll parser -> rent_comps.
Parses a rent-roll attachment (PDF text, or vision for image PDFs) into per-unit
in-place rents and writes one rent_comps row per occupied unit (source rent_roll),
tagged by market + unit_type so Phase-3 market-rent medians can be computed.
Money in DOLLARS (rent_comps.rent is monthly dollars per schema)."""
import json
import os
import re

from ingest.parsers import _client, _extract_json
from ingest import attachments

SYSTEM = ("You extract rent-roll data precisely for a multifamily acquisitions firm. "
          "Only include OCCUPIED units with a real current rent. Never invent values. "
          "Return ONLY valid JSON.")

PROMPT = """Parse this rent roll. Return JSON:
{{"units": [{{"unit_label": str|null, "unit_type": "Studio|1BR|2BR|3BR|4BR",
  "beds": int|null, "baths": number|null, "sqft": int|null,
  "rent": int (monthly, dollars), "occupied": bool}}]}}

- One element per unit. Set occupied=false for vacant/model/down units (no rent).
- unit_type from bed count: 0->Studio, 1->1BR, 2->2BR, etc. Infer beds if only type given.
- Money as plain integers in dollars (monthly rent). Null for anything not present.

RENT ROLL:
\"\"\"
{body}
\"\"\""""


def _call(content, model):
    resp = _client().messages.create(
        model=model, max_tokens=2500, system=SYSTEM,
        messages=[{"role": "user", "content": content}])
    try:
        data = _extract_json(resp.content[0].text)
    except json.JSONDecodeError:
        return {"units": []}
    data.setdefault("units", [])
    return data


def parse_pdf(data, model=None):
    """Return list of unit dicts from a rent-roll PDF (text first, vision fallback)."""
    model = model or os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
    text = attachments.pdf_text(data)
    units = []
    if text and len(text) > 80:
        units = _call(PROMPT.format(body=text[:18000]), model).get("units", [])
    if not units:
        import base64
        imgs = attachments.pdf_to_images(data)
        if imgs:
            content = [{"type": "text", "text": PROMPT.format(body="(see attached page images)")}]
            for img in imgs[:5]:
                content.append({"type": "image", "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": base64.standard_b64encode(img).decode()}})
            units = _call(content, model).get("units", [])
    return units


def write_rent_comps(conn, listing_id, address, market, units, source="rent_roll"):
    """Insert one rent_comps row per occupied unit; returns count written."""
    cur = conn.cursor()
    # replace prior rows from this listing+source so re-runs don't duplicate
    cur.execute("DELETE FROM rent_comps WHERE source_listing_id=%s AND source=%s",
                (listing_id, source))
    n = 0
    for u in units:
        if not u.get("occupied", True) or not u.get("rent"):
            continue
        cur.execute(
            """INSERT INTO rent_comps
               (market, address, unit_type, beds, baths, sqft, rent, source,
                source_listing_id, raw_data)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
            (market, address, u.get("unit_type"), u.get("beds"), u.get("baths"),
             u.get("sqft"), u.get("rent"), source, listing_id, json.dumps(u)))
        n += 1
    return n
