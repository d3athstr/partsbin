"""Claude API parser: turn a vendor order email into structured JSON.

Uses the anthropic SDK (ANTHROPIC_API_KEY from env). Model defaults to
claude-sonnet-5 and can be overridden with PARTSBIN_CLAUDE_MODEL.
"""
import html as html_lib
import json
import os
import re

MODEL = os.getenv('PARTSBIN_CLAUDE_MODEL', 'claude-sonnet-5')
MAX_BODY_CHARS = 24000

VENDORS = ('amazon', 'aliexpress', 'adafruit', 'mouser', 'digikey', 'seeed', 'rokland',
           'jlcpcb', 'pololu')
EVENTS = ('ordered', 'shipped', 'delivered')

# Vendors whose PAYMENT receipts may stand in for a missing order email.
#
# A PayPal receipt is a poor substitute for the real thing: it carries
# PayPal's transaction id rather than the vendor's order number, and usually
# only the merchant and a total, so the order lands with no line items to
# match against inventory. It is therefore allowed ONLY for vendors whose own
# mail cannot reach ingestion at all.
#
# seeed: Seeed mails no-reply@notify.seeed.cc to Don's OUTLOOK address and has
# never once reached his Gmail (verified 2026-08-11 over all time), so without
# this the orders are simply invisible.
#
# Do NOT add a vendor that already mails Gmail directly - Pololu and Adafruit
# both do, and a payment receipt for one of those would create a SECOND order
# under a different number for a purchase already recorded.
PAYMENT_FALLBACK_VENDORS = ('seeed',)

SYSTEM_PROMPT = """You are a strict parser for vendor order emails feeding an \
electronics inventory system. You receive one email (subject, sender, body) \
from Amazon, AliExpress, Adafruit, Mouser, DigiKey, Seeed Studio, Rokland, \
Pololu (Robotics & Electronics) or JLCPCB (a PCB fabricator).

Respond with ONLY a single JSON object - no prose, no explanation, no markdown \
fences. The schema is:

{
  "is_order": boolean,          // true only for order confirmation / shipment / delivery notices
  "vendor": "amazon" | "aliexpress" | "adafruit" | "mouser" | "digikey" | "seeed"
          | "rokland" | "jlcpcb" | "pololu" | "other",
  "order_no": string | null,    // the vendor's order number, verbatim
  "payment_derived": boolean,   // true only for a PAYMENT receipt (PayPal), not a seller email
  "order_no_source": "merchant" | "paypal" | null,   // where order_no came from
  "order_date": string | null,  // ISO-8601 date the order was PLACED (see rules)
  "event": "ordered" | "shipped" | "delivered" | null,
  "items": [                    // line items when present in the email, else []
    {"title": string, "qty": integer, "unit_price": number | null,
     "units_per_item": integer,   // physical units in ONE line-item qty:
                                  // "100Pcs 10k Resistor" -> 100, else 1
     "is_component": boolean,     // plausibly electronics/maker inventory?
     "is_kit": boolean}           // assortment kit of VARYING parts?
  ],
  "tracking": string | null,    // tracking number if present
  "carrier": string | null,     // carrier name if present (UPS, USPS, FedEx, ...)
  "eta": string | null,         // estimated delivery date, ISO-8601 if determinable
  "total": number | null        // ORDER grand total, numeric only, no currency
}

Rules:
- The vendor is whoever SOLD the goods, which is not always who sent the
  email. Much of this mail is FORWARDED from Don's own Outlook address
  (Adafruit, Pololu, sometimes Seeed), so the From header is his address and
  the real vendor is only visible in the forwarded body, subject or an
  "Original Message" block - read those before deciding. Getting this wrong
  files the order under "other", where it is invisible to the vendor filter.
- order_date: the date the purchase was actually made. For a FORWARDED email
  this is the date on the ORIGINAL message ("Sent: August 9, 2026 5:33 PM" in
  the forwarded header), NOT the date it was forwarded, which may be days
  later. null if the email states no date.
- PAYMENT receipts (PayPal "You sent a payment", "Receipt for your payment")
  are NOT the seller's own order email. Handle them like this:
  * vendor = the MERCHANT who was paid, read from the merchant/recipient name,
    never "paypal".
  * A merchant is usually named by its LEGAL ENTITY, not its brand, and that
    name is often not in English. All of the following are vendor "seeed":
    "Seeed Development Limited", "Shenzhen Seeed Technology Co., Ltd",
    "深圳矽递科技股份有限公司" (Shenzhen Seeed Technology), and payment
    addresses such as payment@seeedstudio.com or service@seeed.cc - including
    when PayPal truncates them ("payment@seeedstudio....").
    Translate or transliterate a non-Latin merchant name before deciding, and
    treat the payment address as authoritative when the name is unclear.
  * Set payment_derived=true. This marks the order as reconstructed from a
    payment rather than from the seller, where line items are usually absent.
  * order_no: prefer the MERCHANT's own invoice/order number if the receipt
    shows one. Only if it does not, use PayPal's transaction/receipt id.
    Say which you used in order_no_source: "merchant" or "paypal".
  * items: list them only if the receipt genuinely itemises the cart. A
    single line naming the merchant, or the payment amount restated, is NOT
    an item - return items=[] rather than inventing one.
  * A payment receipt is always event "ordered". Refunds, disputes,
    subscription and donation receipts are is_order=false.
- Marketing, recommendations, review requests, refunds, account notices: is_order=false.
- Delivery delay / "running late" / delivery-date-changed notices: is_order=false.
- "Your order has been placed/confirmed" -> event "ordered".
- "Your package has shipped / is on the way" -> event "shipped".
- "Delivered / your package arrived" -> event "delivered".
- qty defaults to 1 when not stated. Keep item titles as written, trimmed.
- total: the order's grand/order total ("Grand Total", "Order Total"), as a
  bare number. NOT a per-item price, NOT a shipment subtotal when the email
  covers only part of the order. null when not stated.
- NEVER invent an item. Amazon increasingly redacts confirmations down to
  "Ordered: 5 Electronics items" with product images but no titles, prices or
  ASINs anywhere in the email. When the email states an item COUNT but names
  nothing, return items=[] - do not emit placeholder rows like
  {"title": "Electronics item"}. A placeholder is worse than an empty order:
  it becomes a junk line in the review queue and can fuzzy-match a real
  component. is_order stays true so the order itself is still recorded.
- JLCPCB is a PCB FABRICATOR, not a parts store. Its invoices bill a build,
  not a catalogue item. A board-fabrication line ("PCB", "1-2 Layer PCB",
  "'osl-carrier' 5 pcs") IS inventory - the bare board gets stocked:
  is_component=true, is_kit=false, qty = NUMBER OF BOARDS ordered,
  units_per_item=1. Put the board/design name in the title when the email
  gives one, so it can be matched to an existing PCB component.
- JLCPCB non-board charges are NOT components: engineering/setup fees, stencil
  fees, shipping, customs/tax, coupons and discounts -> is_component=false.
  They still count toward the order total.
- units_per_item: pack size stated in the title ("50pcs", "2-pack", "x10");
  1 when unclear. Do NOT multiply it into qty - report them separately.
- is_component: true for anything that belongs in an electronics/maker
  inventory - parts, modules, dev boards, sensors, batteries, wire, tools,
  soldering/prototyping supplies, enclosures, fasteners, 3D-printing gear.
  false for clearly unrelated goods: food, pet supplies, clothing, household,
  toiletries, media. When unsure, use true (a human reviews).
- is_kit: true ONLY for assortments of VARYING parts - mixed values, sizes or
  colors meant to be stocked separately ("525pcs resistor kit 17 values",
  "M2.5 standoff & screw & nut kit", "heat shrink assortment", "LED kit 10
  colors"). A multipack of ONE identical part ("100pcs 10k resistor",
  "5-pack D1 Mini") is NOT a kit. A single product whose box has accessories
  (dev board + cable) is NOT a kit. For kits set units_per_item=1 so qty
  counts KITS, never loose pieces.
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
        is_kit = bool(item.get('is_kit', False))
        items.append({'title': title, 'qty': qty, 'unit_price': unit_price,
                      'units_per_item': 1 if is_kit else units,
                      'is_component': bool(item.get('is_component', True)),
                      'is_kit': is_kit})

    order_no = parsed.get('order_no')

    # A payment receipt only counts as an order for vendors whose own mail
    # cannot reach us (PAYMENT_FALLBACK_VENDORS). For anyone else it would
    # duplicate an order the seller's own email already created.
    payment_derived = bool(parsed.get('payment_derived'))
    if payment_derived and vendor not in PAYMENT_FALLBACK_VENDORS:
        return {'is_order': False, 'vendor': vendor, 'order_no': None,
                'event': None, 'items': [], 'total': None, 'tracking': None,
                'carrier': None, 'eta': None, 'payment_derived': True,
                'order_no_source': None, 'skipped_reason': 'payment receipt for a vendor that mails us directly'}

    # Grand total. Kept even when items is empty - a redacted Amazon
    # confirmation ("Ordered: 5 Electronics items") carries no titles at all,
    # so the total is the only substance the order has.
    try:
        total = parsed.get('total')
        total = round(float(total), 2) if total is not None else None
        if total is not None and total <= 0:
            total = None
    except (ValueError, TypeError):
        total = None

    order_date = parsed.get('order_date')
    if order_date:
        # Trust only a plain ISO date; anything else falls back to the
        # message's own Date header in the pipeline.
        order_date = str(order_date).strip()[:10]
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', order_date):
            order_date = None

    return {
        'total': total,
        'order_date': order_date,
        'payment_derived': payment_derived,
        'order_no_source': (str(parsed.get('order_no_source')).lower()
                            if parsed.get('order_no_source') in ('merchant', 'paypal')
                            else None),
        'is_order': bool(parsed.get('is_order')),
        'vendor': vendor,
        'order_no': str(order_no).strip() if order_no else None,
        'event': event,
        'items': items,
        'tracking': (str(parsed.get('tracking')).strip() or None) if parsed.get('tracking') else None,
        'carrier': (str(parsed.get('carrier')).strip() or None) if parsed.get('carrier') else None,
        'eta': (str(parsed.get('eta')).strip() or None) if parsed.get('eta') else None,
    }


def _html_to_text(body):
    """Crude HTML -> text so the char cap spends its budget on content.

    AliExpress order emails are HTML-only and mostly CSS; raw-capping at
    MAX_BODY_CHARS used to truncate before the first line item appeared.
    """
    body = re.sub(r'(?is)<(style|script|head)[^>]*>.*?</\1>', ' ', body)
    body = re.sub(r'(?is)<br\s*/?>|</(p|div|tr|li|h[1-6])>', '\n', body)
    body = re.sub(r'(?s)<[^>]+>', ' ', body)
    body = html_lib.unescape(body)
    body = re.sub(r'[ \t]+', ' ', body)
    body = re.sub(r'\n\s*\n+', '\n', body)
    return body.strip()


def parse_order_email(subject, sender, body):
    """Parse one order email with Claude.

    Args:
        subject: email subject
        sender: From header
        body: plain-text (preferred) or HTML body

    Returns:
        dict in the normalized order-email shape, or None when parsing failed
    """
    body = body or ''
    if '<' in body and ('</' in body or '/>' in body or '<br' in body.lower()):
        body = _html_to_text(body)
    body = body[:MAX_BODY_CHARS]

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
of item titles (from Amazon/AliExpress/Adafruit/Mouser/DigiKey/Seeed/Rokland/Pololu/JLCPCB \
orders) and a \
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
      "units_per_item": integer,   // units in ONE ordered item: "100pcs ..." -> 100, else 1
      "is_kit": boolean            // assortment of VARYING values/sizes/colors?
    }
  ]
}

Rules:
- Names should be searchable and deduplicatable: value + key spec + package/form
  factor. Strip marketing fluff ("Hot Sale", "for Arduino DIY Kit", emoji).
- Multi-packs: "5PCS ESP32-S3 DevKitC" -> name the single unit, units_per_item=5.
- Assorted kits of VARYING parts (e.g. "600pcs resistor kit 10ohm-1M",
  "standoff & screw & nut kit", "heat shrink assortment"): set is_kit=true
  and units_per_item=1, and still return ONE definition describing the kit
  (the caller explodes kits separately). A multipack of one identical part
  is NOT a kit (is_kit=false, units_per_item=pack size).
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
        comp['is_kit'] = bool(comp.get('is_kit', False))
        results.append(comp)
    return results
