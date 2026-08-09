"""Kit breakout: research an assortment kit's real contents via web search.

An order item flagged is_kit (a "525pcs resistor kit, 17 values" style
assortment) should never land in stock as one lump - the useful inventory is
the individual values with their per-value counts. Those counts are almost
never in the order email, but they ARE on the product listing (feature
bullets, box-lid photo, "package included" section), so we ask Claude to go
read the listing with the same web_search/web_fetch tooling enrichment uses.

Used by POST /api/orders/<id>/auto-create-components, which explodes a kit
item into per-part child OrderItems from what this module returns. Research
that can't be verified returns found=False and the kit falls back to being
stocked as a single component (the pre-2026-07-16 behavior).
"""
import json

from app.ingest.claude_parser import MODEL, _client, _extract_json

KIT_SYSTEM = """You determine the exact contents of an electronics assortment \
kit for an inventory system. You receive the raw order-item title of a kit \
(from Amazon/AliExpress/Adafruit/Mouser/DigiKey/Seeed) and a list of allowed \
inventory categories.

Use web search to find the EXACT product listing, then extract the per-part
piece breakdown of one kit. The breakdown usually lives in the listing's
feature bullets, the "Package Included" section of the description, or a
piece-count grid printed on the box/case in a product photo - fetch the
listing page (and open gallery images when the text has no breakdown).

Respond with ONLY one JSON object - no prose, no markdown fences:

{
  "found": boolean,             // true only if you VERIFIED the breakdown
  "confidence": "high"|"medium"|"low",
  "source_url": string|null,    // the listing/page the breakdown came from
  "total_pieces": integer|null, // advertised piece count of one kit, if known
  "parts": [
    {
      "name": string,           // canonical single-part name, e.g. "220Ω ±1% Metal Film Resistor (1/4W)"
      "category": string,       // MUST be one of the allowed categories
      "qty_per_kit": integer,   // pieces of this exact part in ONE kit
      "manufacturer": string|null,
      "mpn": string|null,
      "description": string|null,
      "specs": {}               // short key/value specs (resistance, size, thread...)
    }
  ]
}

Rules:
- Parts are what a maker stocks separately: each resistor value, each
  standoff length, each heat-shrink diameter, each LED color. Shared traits
  (tolerance, power rating, material) go in each part's name/specs.
- qty_per_kit counts come ONLY from the listing you found. The parts' counts
  should sum to the advertised total; if they don't, or you can only find the
  value list but not the per-value counts, set found=false. NEVER guess or
  evenly split.
- Make sure the listing matches the ordered title (piece count, value count,
  brand). A same-brand kit in a different size is the wrong listing.
- Include non-stocked extras (install tip, storage case) as parts only when
  they are genuinely reusable items; ignore packaging.
- Names should be searchable and deduplicatable: value + key spec + form
  factor, no marketing fluff.
- If the listing cannot be found or the breakdown cannot be verified,
  return {"found": false, ...} with parts=[]. A wrong breakdown corrupts
  inventory; an honest "not found" just leaves the kit whole."""


def research_kit_contents(title, categories, vendor=None):
    """Web-research one kit title. Returns a normalized dict or None.

    Returns:
        {'found': bool, 'confidence': str, 'source_url': str|None,
         'total_pieces': int|None, 'parts': [{name, category, qty_per_kit,
         manufacturer, mpn, description, specs}]}
        None when the Claude call itself failed.
    """
    prompt = (
        f"Allowed categories: {', '.join(categories)}\n\n"
        f"Vendor: {vendor or 'unknown'}\n"
        f"Kit order-item title: {title}"
    )
    client = _client()
    try:
        try:
            response = client.beta.messages.create(
                model=MODEL,
                max_tokens=6000,
                system=KIT_SYSTEM,
                tools=[
                    {'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 5},
                    {'type': 'web_fetch_20250910', 'name': 'web_fetch', 'max_uses': 5},
                ],
                betas=['web-fetch-2025-09-10'],
                messages=[{'role': 'user', 'content': prompt}],
            )
        except Exception:
            response = client.messages.create(
                model=MODEL,
                max_tokens=6000,
                system=KIT_SYSTEM,
                tools=[{'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 6}],
                messages=[{'role': 'user', 'content': prompt}],
            )
    except Exception:
        return None

    # With server tools the answer is the LAST text block
    text = ''
    for block in response.content:
        if block.type == 'text':
            text = block.text
    return _normalize_breakdown(_extract_json(text), categories)


def _normalize_breakdown(data, categories):
    """Validate/coerce a raw breakdown payload. Returns dict or None."""
    if not isinstance(data, dict):
        return None

    valid_categories = set(categories)
    parts = []
    for part in data.get('parts') or []:
        if not isinstance(part, dict):
            continue
        name = str(part.get('name') or '').strip()
        try:
            qty = int(part.get('qty_per_kit') or 0)
        except (ValueError, TypeError):
            qty = 0
        if not name or qty <= 0:
            continue
        category = str(part.get('category') or '').strip()
        if category not in valid_categories:
            category = 'Other'
        specs = part.get('specs')
        parts.append({
            'name': name[:200],
            'category': category,
            'qty_per_kit': qty,
            'manufacturer': (str(part['manufacturer']).strip() or None)
                            if part.get('manufacturer') else None,
            'mpn': (str(part['mpn']).strip() or None) if part.get('mpn') else None,
            'description': (str(part['description']).strip() or None)
                           if part.get('description') else None,
            'specs': specs if isinstance(specs, dict) else {},
        })

    total = data.get('total_pieces')
    try:
        total = int(total) if total is not None else None
    except (ValueError, TypeError):
        total = None

    found = bool(data.get('found')) and len(parts) >= 2
    confidence = str(data.get('confidence') or 'low').lower()
    if confidence not in ('high', 'medium', 'low'):
        confidence = 'low'

    source_url = data.get('source_url')
    source_url = str(source_url).strip()[:500] if source_url else None

    return {
        'found': found,
        'confidence': confidence,
        'source_url': source_url,
        'total_pieces': total,
        'parts': parts,
    }
