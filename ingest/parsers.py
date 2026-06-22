"""Parsers for the Deal Flow pipeline.
- html_to_text: strip an HTML email body to readable text.
- ai_extract: Claude API extraction of listing(s) from free-form email/forward text,
  returning the PROMPTS.md field set, wrapped in a `listings` array to handle
  multi-listing digests and to noise-filter newsletters (empty list = no real deal).
Money returned as integer DOLLARS (converted to cents at insert time).
"""
import json
import os
import re

from bs4 import BeautifulSoup
import anthropic

from ingest.gmail_client import _load_env

# JSON schema we ask the model to fill, per PROMPTS.md (+ multi-listing wrapper).
LISTING_FIELDS = (
    "address, city, state, zip, units, asking_price, year_built, building_sf, "
    "lot_sf, unit_mix (array of {type, count, avg_rent}), gross_revenue, "
    "total_expenses, noi, vacancy_rate, broker_name, broker_email, listing_date "
    "(YYYY-MM-DD), external_id (MLS number if present)"
)

SYSTEM = (
    "You extract structured multifamily real-estate listing data from broker emails "
    "for an acquisitions firm. Be precise; never invent values. Return ONLY valid JSON."
)

PROMPT_TMPL = """Extract every distinct property listing from this broker email{src}.

Return JSON of the exact shape:
{{"listings": [{{ {fields} }}]}}

Rules:
- One array element per distinct property. Multi-listing digests -> multiple elements.
- If the email contains NO actual property listing (event/meetup invite, newsletter
  chatter, pure notification with no deal), return {{"listings": []}}.
- Set any unavailable field to null. Money as plain integers in DOLLARS (no symbols/commas).
- If this is a FORWARDED email, extract the deal from the forwarded content and set
  broker_name/broker_email from the ORIGINAL sender if visible.

EMAIL:
\"\"\"
{body}
\"\"\""""


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    text = soup.get_text("\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _client():
    _load_env()
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    start = text.find("{")
    if start > 0:
        text = text[start:]
    return json.loads(text)


def _finish(resp):
    raw = resp.content[0].text
    try:
        data = _extract_json(raw)
    except json.JSONDecodeError:
        return {"listings": [], "_parse_error": raw[:500]}
    data.setdefault("listings", [])
    data["_usage"] = {"in": resp.usage.input_tokens, "out": resp.usage.output_tokens}
    return data


def ai_extract(body_text: str, source_label: str = "", model: str = None) -> dict:
    """Return {'listings': [...]} extracted from email text. Truncates very long bodies."""
    model = model or os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
    body = body_text[:18000]
    src = f" (sender/source: {source_label})" if source_label else ""
    prompt = PROMPT_TMPL.format(src=src, fields=LISTING_FIELDS, body=body)
    resp = _client().messages.create(
        model=model, max_tokens=3000, system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return _finish(resp)


def ai_extract_images(images, source_label: str = "", model: str = None) -> dict:
    """Extract listings from image-based PDFs (rendered pages) via Claude vision.
    `images` = list of PNG byte strings."""
    import base64
    model = model or os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
    src = f" (sender/source: {source_label})" if source_label else ""
    prompt = PROMPT_TMPL.format(src=src, fields=LISTING_FIELDS,
                               body="(content is provided as the attached page images)")
    content = [{"type": "text", "text": prompt}]
    for img in images[:5]:
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/png",
            "data": base64.standard_b64encode(img).decode()}})
    resp = _client().messages.create(
        model=model, max_tokens=3000, system=SYSTEM,
        messages=[{"role": "user", "content": content}],
    )
    return _finish(resp)
