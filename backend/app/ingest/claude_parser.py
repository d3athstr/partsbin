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
    {"title": string, "qty": integer, "unit_price": number | null}
  ],
  "tracking": string | null,    // tracking number if present
  "carrier": string | null,     // carrier name if present (UPS, USPS, FedEx, ...)
  "eta": string | null          // estimated delivery date, ISO-8601 if determinable
}

Rules:
- Marketing, recommendations, review requests, refunds, account notices: is_order=false.
- "Your order has been placed/confirmed" -> event "ordered".
- "Your package has shipped / is on the way" -> event "shipped".
- "Delivered / your package arrived" -> event "delivered".
- qty defaults to 1 when not stated. Keep item titles as written, trimmed.
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
        items.append({'title': title, 'qty': qty, 'unit_price': unit_price})

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
