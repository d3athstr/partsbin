"""Claude API parser: turn a vendor order email into structured JSON.

Uses the anthropic SDK (ANTHROPIC_API_KEY from env). Model defaults to
claude-sonnet-5 and can be overridden with PARTSBIN_CLAUDE_MODEL.
"""
import json
import os
import re

MODEL = os.getenv('PARTSBIN_CLAUDE_MODEL', 'claude-sonnet-5')
MAX_BODY_CHARS = 24000

VENDORS = ('amazon', 'aliexpress', 'adafruit', 'mouser', 'digikey')
EVENTS = ('ordered', 'shipped', 'delivered')

SYSTEM_PROMPT = """You are a strict parser for vendor order emails feeding an \
electronics inventory system. You receive one email (subject, sender, body) \
from Amazon, AliExpress, Adafruit, Mouser or DigiKey.

Respond with ONLY a single JSON object - no prose, no explanation, no markdown \
fences. The schema is:

{
  "is_order": boolean,          // true only for order confirmation / shipment / delivery notices
  "vendor": "amazon" | "aliexpress" | "adafruit" | "mouser" | "digikey" | "other",
  "order_no": string | null,    // the vendor's order number, verbatim
  "event": "ordered" | "shipped" | "delivered" | null,
  "items": [                    // line items when present in the email, else []
    {"title": string, "qty": integer, "unit_price": number | null,
     "units_per_item": integer,   // physical units in ONE line-item qty:
                                  // "100Pcs 10k Resistor" -> 100, else 1
     "is_component": boolean}     // plausibly electronics/maker inventory?
  ],
  "tracking": string | null,    // tracking number if present
  "carrier": string | null,     // carrier name if present (UPS, USPS, FedEx, ...)
  "eta": string | null          // estimated delivery date, ISO-8601 if determinable
}

Rules:
- Marketing, recommendations, review requests, refunds, account notices: is_order=false.
- Delivery delay / "running late" / delivery-date-changed notices: is_order=false.
- "Your order has been placed/confirmed" -> event "ordered".
- "Your package has shipped / is on the way" -> event "shipped".
- "Delivered / your package arrived" -> event "delivered".
- qty defaults to 1 when not stated. Keep item titles as written, trimmed.
- units_per_item: pack size stated in the title ("50pcs", "2-pack", "x10");
  1 when unclear. Do NOT multiply it into qty - report them separately.
- is_component: true for anything that belongs in an electronics/maker
  inventory - parts, modules, dev boards, sensors, batteries, wire, tools,
  soldering/prototyping supplies, enclosures, fasteners, 3D-printing gear.
  false for clearly unrelated goods: food, pet supplies, clothing, household,
  toiletries, media. When unsure, use true (a human reviews).
- If is_order is false, all other fields may be null/empty."""


def _client():
    import anthropic
    return anthropic.Anthropic()


def _extract_json(text):
    """Tolerate fenced or prose-wrapped output; return a dict or None"""
    if not text:
        return None

    # Strip markdown fences if present
    fenced = re.search(r'```(?:json)?\s*(.*?)```', text, re.DOTALL)
    if fenced:
        text = fenced.group(1)

    # Trim to the outermost object
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = text[start:end + 1]

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # Common repair: trailing commas before } or ]
        repaired = re.sub(r',\s*([}\]])', r'\1', candidate)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            return None


def _normalize(parsed):
    """Coerce the parsed payload into the expected shape"""
    if not isinstance(parsed, dict):
        return None

    vendor = str(parsed.get('vendor') or 'other').lower()
    if vendor not in VENDORS:
        vendor = 'other'

    event = parsed.get('event')
    if event not in EVENTS:
        event = 'ordered' if parsed.get('is_order') else None

    items = []
    for item in parsed.get('items') or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get('title') or '').strip()
        if not title:
            continue
        try:
            qty = max(int(item.get('qty') or 1), 1)
        except (ValueError, TypeError):
            qty = 1
        unit_price = item.get('unit_price')
        try:
            unit_price = float(unit_price) if unit_price is not None else None
        except (ValueError, TypeError):
            unit_price = None
        try:
            units = max(int(item.get('units_per_item') or 1), 1)
        except (ValueError, TypeError):
            units = 1
        items.append({'title': title, 'qty': qty, 'unit_price': unit_price,
                      'units_per_item': units,
                      'is_component': bool(item.get('is_component', True))})

    order_no = parsed.get('order_no')

    return {
        'is_order': bool(parsed.get('is_order')),
        'vendor': vendor,
        'order_no': str(order_no).strip() if order_no else None,
        'event': event,
        'items': items,
        'tracking': (str(parsed.get('tracking')).strip() or None) if parsed.get('tracking') else None,
        'carrier': (str(parsed.get('carrier')).strip() or None) if parsed.get('carrier') else None,
        'eta': (str(parsed.get('eta')).strip() or None) if parsed.get('eta') else None,
    }


def parse_order_email(subject, sender, body):
    """Parse one order email with Claude.

    Args:
        subject: email subject
        sender: From header
        body: plain-text (preferred) or HTML body

    Returns:
        dict in the normalized order-email shape, or None when parsing failed
    """
    body = (body or '')[:MAX_BODY_CHARS]

    response = _client().messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{
            'role': 'user',
            'content': (
                f'Subject: {subject}\n'
                f'From: {sender}\n'
                f'---\n'
                f'{body}'
            ),
        }],
    )

    text = next((block.text for block in response.content if block.type == 'text'), '')
    return _normalize(_extract_json(text))


# ==================== Component inference (review-queue auto-create) ====================

COMPONENT_SYSTEM_PROMPT = """You turn raw vendor order-item titles into clean \
component definitions for an electronics inventory. You receive a numbered list \
of item titles (from Amazon/AliExpress/Adafruit/Mouser/DigiKey orders) and a \
list of allowed categories.

Respond with ONLY a single JSON object - no prose, no markdown fences:

{
  "components": [
    {
      "index": integer,            // matches the input item number
      "name": string,              // concise canonical name, e.g. "0.1uF 50V Ceramic Capacitor (0805)"
      "category": string,          // MUST be one of the allowed categories
      "manufacturer": string|null, // only if clearly identifiable (e.g. "Espressif", "Adafruit")
      "mpn": string|null,          // manufacturer part number if present in the title
      "description": string|null,  // one short sentence, only if it adds information
      "specs": {  },               // key/value specs pulled from the title, e.g.
                                   // {"resistance": "10k", "tolerance": "1%", "package": "0603"}
      "units_per_item": integer    // units in ONE ordered item: "100pcs ..." -> 100, else 1
    }
  ]
}

Rules:
- Names should be searchable and deduplicatable: value + key spec + package/form
  factor. Strip marketing fluff ("Hot Sale", "for Arduino DIY Kit", emoji).
- Multi-packs: "5PCS ESP32-S3 DevKitC" -> name the single unit, units_per_item=5.
- Assorted kits (e.g. "600pcs resistor kit 10ohm-1M") stay ONE component
  (category fits the parts, units_per_item=1) - do not explode kits.
- If a title is not really an electronic component (gift, household item),
  still return an entry with your best category ("Other") - the human decides.
- specs values are short strings; omit unknown fields rather than guessing."""


def infer_components(titles, categories):
    """Infer component definitions from raw order-item titles (one Claude call).

    Args:
        titles: list of raw item title strings
        categories: allowed category names

    Returns:
        list aligned with titles; each entry is a dict (name/category/specs/...)
        or None when inference failed for that title.
    """
    if not titles:
        return []

    numbered = '\n'.join(f'{i + 1}. {t}' for i, t in enumerate(titles))
    prompt = (
        f"Allowed categories: {', '.join(categories)}\n\n"
        f"Items:\n{numbered}"
    )

    response = _client().messages.create(
        model=MODEL,
        max_tokens=4096,
        system=COMPONENT_SYSTEM_PROMPT,
        messages=[{'role': 'user', 'content': prompt}],
    )
    text = next((block.text for block in response.content if block.type == 'text'), '')
    data = _extract_json(text)
    if not data or not isinstance(data.get('components'), list):
        return [None] * len(titles)

    by_index = {}
    for comp in data['components']:
        if isinstance(comp, dict) and isinstance(comp.get('index'), int):
            by_index[comp['index'] - 1] = comp

    results = []
    for i in range(len(titles)):
        comp = by_index.get(i)
        if not comp or not (comp.get('name') or '').strip():
            results.append(None)
            continue
        units = comp.get('units_per_item')
        comp['units_per_item'] = units if isinstance(units, int) and units > 0 else 1
        results.append(comp)
    return results
