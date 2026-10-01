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
           'jlcpcb', 'pololu', 'ebay', 'polycase', 'onlinemetals', 'yakima',
           'eletechsup', 'coldandcolder', 'ti')
EVENTS = ('ordered', 'shipped', 'delivered')

# Vendors whose PAYMENT receipts may stand in for a missing order email.
#
# EMPTY SINCE 2026-10-01 (Don): PayPal receipts are no longer ingested for ANY
# vendor - "they aren't providing useful data". Every payment-derived order was
# a total and PayPal's transaction id with zero line items, so nothing ever
# matched inventory (a JLCPCB board order on 2026-10-01 was
# the last straw). The parser still classifies receipts (payment_derived=true)
# so this gate can drop them deterministically. JLCPCB now files from its own
# "Order Review # W... Completed" email instead - see the JLCPCB prompt rules.
# Seeed and eBay have NO other path: their own mail goes to Outlook, so those
# purchases appear only if the seller's own email is forwarded to the mailbox.
#
# History below kept for context.
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
# ebay: same situation, verified 2026-08-12 - from:ebay matches ZERO Gmail
# messages over the past year because Don's eBay account is bound to his
# Outlook address. The forwarded PayPal receipt is the only path, so without
# this eBay purchases are invisible. Expect thin orders: eBay's receipts name
# the merchant as the marketplace entity "eBay Commerce Inc." and itemise
# nothing, so these land as a date + total with items=[] for Don to fill in.
#
# Do NOT add a vendor that already mails Gmail directly - Pololu and Adafruit
# both do, and a payment receipt for one of those would create a SECOND order
# under a different number for a purchase already recorded.
# jlcpcb: verified 2026-08-12. JLCPCB DOES mail Gmail, but never with an order
# confirmation - across the whole account it sends only a signup code, marketing,
# and "Order Review # ... Completed" status mail. A status email cannot create an
# order (it only upgrades an existing one), so there is nothing here for a payment
# receipt to duplicate and the guard above is satisfied.
# Order W2026081221439587 (6 boards, .71, paid by PayPal via the Outlook
# forward) was invisible in PartsBin because BOTH paths dead-ended: the receipt was
# dropped right here, and the review email was dropped as a status-with-no-order.
# Both got ProcessedMessage rows, so neither would EVER have been retried.
# Expect thin orders - JLCPCB bills a build and the PayPal receipt itemises nothing.
PAYMENT_FALLBACK_VENDORS = ()

SYSTEM_PROMPT = """You are a strict parser for vendor order emails feeding an \
electronics inventory system. You receive one email (subject, sender, body) \
from Amazon, AliExpress, Adafruit, Mouser, DigiKey, Seeed Studio, Rokland, \
Pololu (Robotics & Electronics), JLCPCB (a PCB fabricator), eBay, Polycase \
(plastic and aluminium enclosures), OnlineMetals (cut-to-size metal and \
plastic stock), Yakima (roof-rack towers, crossbars and mounts), Eletechsup \
(RS485/Modbus relay and I/O boards, DIN-rail control modules) or Cold & Colder \
(silicone tubing, Peltier/thermoelectric cooling parts and water-cooling gear) \
or the Texas Instruments TI.com store (TI's own ICs, evaluation modules and \
LaunchPad boards).

Respond with ONLY a single JSON object - no prose, no explanation, no markdown \
fences. The schema is:

{
  "is_order": boolean,          // true only for order confirmation / shipment / delivery notices
  "vendor": "amazon" | "aliexpress" | "adafruit" | "mouser" | "digikey" | "seeed"
          | "rokland" | "jlcpcb" | "pololu" | "ebay" | "polycase" | "onlinemetals"
          | "yakima" | "eletechsup" | "coldandcolder" | "ti" | "other",
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
  "total": number | null,       // ORDER grand total, numeric only, no currency
  "items_total": integer | null // line count the ORDER has, ONLY when the email
                                // says it shows fewer ("10 of 17 parts displayed")
}

Rules:
- The vendor is whoever SOLD the goods, which is not always who sent the
  email. Much of this mail is FORWARDED from Don's own Outlook address
  (Adafruit, Pololu, sometimes Seeed), so the From header is his address and
  the real vendor is only visible in the forwarded body, subject or an
  "Original Message" block - read those before deciding. Getting this wrong
  files the order under "other", where it is invisible to the vendor filter.
- MERCHANT ALIASES. Several vendors bill under a corporate name that shares no
  words with the storefront. Map these to the vendor slug, wherever they
  appear (From header, body, invoice header, or a payment receipt's merchant):
  * "ThyssenKrupp Online Metals, LLC", "thyssenkrupp Online Metals",
    "Thyssenkrupp Online", "thyssenkrupp Materials NA", "TKMNA", and the
    2026-06-10 rebrand "tk accelis" / "tk accelis Materials Plus"
    -> vendor "onlinemetals". OnlineMetals.com has been a thyssenkrupp company
    since 2007 and is the ONLY thyssenkrupp entity PartsBin buys from.
    Do NOT map any thyssenkrupp name to "polycase" - Polycase, Inc. (Avon,
    Ohio, enclosures) is unrelated and independently owned.
  * "Polycase, Inc." / "Polycase Inc" / "ECP" -> vendor "polycase".
  * "Yakima Products, Inc." -> vendor "yakima".
  * "Eletechsup", "Eletechsup Retail Original Factory Store", "485IO",
    "485io.com", "Shenzhen Eletechsup Technology" and any Shenzhen/Chinese
    legal entity whose receipt carries the eletechsup.com or 485io.com store
    domain -> vendor "eletechsup". 485io.com is the same company's other
    storefront, not a separate vendor.
  * "Cold & Colder", "Cold and Colder", "ColdandColder", "Cold & Colder LLC"
    (Sheridan, Wyoming) -> vendor "coldandcolder".
  * "Texas Instruments", "Texas Instruments Incorporated", "TI", "TI Store",
    "TI.com" and any ti.com sending address -> vendor "ti".
  * "Digi-Key", "Digi-Key Electronics", "Digi-Key Corporation", "DigiKey",
    and any digikey.com address (orders@t.digikey.com) -> vendor "digikey".
- TEXAS INSTRUMENTS IS A BRAND ON EVERY DISTRIBUTOR. Most TI parts are bought
  from DigiKey, Mouser, Amazon or AliExpress, and those orders keep THAT
  vendor - a DigiKey order full of TI chips is vendor "digikey". Only an order
  placed on TI's own store (ti.com, "TI Store", "Texas Instruments" order
  confirmation or shipment notice) is vendor "ti".
- BRAND IS NOT VENDOR ON A MARKETPLACE. Eletechsup and Cold & Colder also sell
  through Amazon, eBay, AliExpress and Etsy storefronts. The vendor is where
  the ORDER WAS PLACED, not whose product it is: an Amazon confirmation that
  happens to contain an eletechsup relay board is vendor "amazon", and an eBay
  or PayPal receipt for a Cold & Colder purchase is vendor "ebay". The brand
  belongs in the item TITLE, never in the vendor field. Only the store's own
  order mail (from eletechsup.com / 485io.com / coldandcolder.com, typically a
  Shopify "Order #1234 confirmed") files as "eletechsup" / "coldandcolder".
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
  * eBay pays through the marketplace entity, so the merchant on the receipt
    reads "eBay Commerce Inc." (also "eBay Inc.", "eBay Marketplaces GmbH",
    or a help address like https://eBay.com/help) -> vendor "ebay". The
    actual seller is a third party the receipt never names; do NOT try to
    guess one, and do not file it under "other" for lack of a seller.
  * An eBay receipt's "Order ID" is a checkout id - a bare UUID
    ("c4bda27b-f77b-4201-ad5c-31f0bb7810ff") or a versioned one
    ("v2_7b29524f-...-5671c62ae6ea_2_6") - NOT an eBay order number, which
    looks like "12-13456-78901". Use it as order_no so the order can be
    deduplicated, but set order_no_source="paypal", never "merchant".
  * eBay receipts itemise NOTHING. The block reading "Purchase amount /
    Qty: 1 / $38.33" is the payment restated, not a line item - return
    items=[]. There is no product title anywhere in that email; do not
    invent one from the merchant name or the subject line.
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
- JLCPCB never sends an order confirmation. Its "Order Review # W... Completed"
  email IS the order record: is_order=true, event "ordered", order_no = the
  W-number verbatim (e.g. "W2026010112345678"), order_no_source "merchant",
  payment_derived=false, total=null (the email states none). Each design it
  lists ("a912d97ffd95_sentinel-dog-revA...", "Approved") is ONE board item.
- JLCPCB "Your JLCPCB Order Is On Its Way" -> event "shipped", order_no = the
  W-number in "Items in this shipment: [W...]", tracking from "Tracking
  Number", carrier as written ("Global Standard Direct Line" etc.). List its
  designs as items too, with the "N pcs" count as qty.
- JLCPCB design names: the upload adds a 12-hex-character prefix and an
  underscore ("a912d97ffd95_") and the email may truncate with "..." - drop
  both, and drop a trailing "-gerbers" / "_Y19"-style suffix. Title the item
  "<design> PCB", e.g. "sentinel-dog-revA PCB". qty = the "N pcs" count when
  the email states one; the review email states none, so use 5 (JLCPCB's
  minimum) there.
- JLCPCB non-board charges are NOT components: engineering/setup fees, stencil
  fees, shipping, customs/tax, coupons and discounts -> is_component=false.
  They still count toward the order total.
- Polycase sells ENCLOSURES. The enclosure itself is inventory
  (is_component=true), and so are its accessories that get stocked: lids,
  gaskets, mounting flanges, DIN clips, screw packs. Its CUSTOMISATION and
  service charges are NOT components: CNC machining, cutouts, digital
  printing, silkscreen, tooling/setup fees, artwork or proof charges,
  shipping, tax -> is_component=false. They still count toward the total.
  A colour/size variant in the title is a variant, never a kit.
- OnlineMetals sells RAW STOCK cut to size (aluminium/brass/steel/acrylic/
  Delrin sheet, plate, bar, rod, tube, angle). A stock line IS inventory:
  is_component=true, is_kit=false, qty = number of PIECES ordered, and keep
  the alloy, temper, profile and the cut dimensions in the title verbatim
  ("6061-T6 Aluminum Sheet 0.125\" x 6\" x 12\"") - those dimensions are the
  part identity and a later order of the same alloy in a different size is a
  DIFFERENT component. Its per-cut charges are NOT components: cutting/saw
  fees, tolerance or squaring charges, drop/remnant fees, handling, shipping,
  fuel surcharge, tax -> is_component=false.
- Yakima sells ROOF-RACK hardware. Towers, crossbars, landing pads, fit
  kits, clips, locks, cores, mounts and their fasteners are inventory
  (is_component=true) - keep the model/part name and any bar length in the
  title, since a fit kit is vehicle-specific and two lengths of the same bar
  are different components. Vehicle-fit lookups, warranty registrations,
  assembly service, shipping and tax -> is_component=false. A "fit kit"
  containing brackets for ONE vehicle is not an assortment: is_kit=false.
- Eletechsup sells INDUSTRIAL CONTROL BOARDS: RS485/Modbus RTU relay boards,
  digital-IO and analog modules, DIN-rail enclosed controllers, UART/TTL and
  Ethernet boards, plus the DIN rail, cases and supplies that go with them.
  All of that is inventory (is_component=true). Its identity is a terse
  alphanumeric model code ("R4D8A08", "N4ROE16", "10IOA08", "DN22D08",
  "R413E16") - keep the model code AND the channel count AND the supply
  voltage in the title verbatim ("R4D8A08 DC 12V 8CH RS485 Relay Board"),
  because the same family in 5V/12V/24V or 4/8/16 channels is a DIFFERENT
  component, not a re-order. A multi-channel board is ONE product, never an
  assortment: is_kit=false. A listing quantity in the title ("(1pcs)",
  "(2pcs)", "5PCS") is the PACK SIZE -> units_per_item, not qty. Shipping,
  tax and customs -> is_component=false.
- Cold & Colder sells SILICONE TUBING and THERMOELECTRIC COOLING parts: tubing
  by length, Peltier/TEC modules ("TEC1-12706"), water blocks, pumps,
  radiators, fans, thermal sheets and pads, and assembled water-cooling kits.
  All inventory (is_component=true). Tubing behaves like cut stock - keep the
  ID, OD and LENGTH in the title verbatim ("1/4\" ID x 3/8\" OD Silicone
  Tubing 10 ft"), since the same tubing in another size is a DIFFERENT
  component; set units_per_item=1 and leave the length in the title rather
  than exploding feet into pieces. A water-cooling kit of MATCHED parts
  (block + pump + radiator + tubing) is a single product, is_kit=false - it
  is not an assortment of varying values to be stocked separately. Shipping
  and tax -> is_component=false.
- DigiKey: order_no is the SALES ORDER number ("Your salesorder number is
  12345678", "Sales order number: 12345678"). A DigiKey shipment notice ALSO
  carries an INVOICE number, and puts it in the SUBJECT ("DigiKey has shipped
  a package for invoice 987654321") - the invoice number is NEVER order_no;
  using it files the shipment as a second, duplicate order. One sales order
  can ship as several invoices. A line item shows a description, a DigiKey
  part number ("296-25616-1-ND") and a Manufacturer part number
  ("TPS63020DSJR"):
  title = the description followed by "(MPN <manufacturer part number>,
  DigiKey <digikey part number>)", e.g. "IC REG BUCK BOOST ADJ 4A 14VSON
  (MPN TPS63020DSJR, DigiKey 296-25616-1-ND)" - the MPN is the part identity, the
  description alone is too terse to match. Use the "Unit price" field as
  unit_price. Shipping, tax, tariff and Digi-Reel/reeling fees are NOT items;
  reeling fees still count toward the total. "Backorder" is a COLUMN on a
  line, not a separate charge: qty = Quantity + Backorder. A line reading
  "Quantity 0 / Backorder 10" is still an item with qty 10 - it is bought,
  just not shipping yet (2026-10-01: a fully backordered 10uF cap was dropped).
  DigiKey's confirmation shows at most ~10 lines and then says "10 of 17 parts
  displayed": list what is shown and set items_total to the 17. A part sold
  as Cut Tape / Tape & Reel / Digi-Reel is still qty = PIECES with
  units_per_item=1. A shipment notice that lists no line items -> items=[].
- Texas Instruments (vendor "ti") sells its own ICs, evaluation modules (EVMs)
  and LaunchPad / BoosterPack dev boards. All are inventory
  (is_component=true). Keep TI's ORDERABLE part number verbatim in the title
  ("TPS63020DSJR", "LP-MSPM0G3507", "BQ25895RTWR") together with any
  description the email gives: the package and reel suffix (DSJR vs DSJT, RGER
  vs RGET) is part of the identity, so do not trim or normalise it. qty =
  PIECES (TI ships cut tape and tubes, not packs), units_per_item=1 unless the
  line says otherwise. An EVM or LaunchPad is ONE product, is_kit=false. Free
  samples are real items: keep them with unit_price 0. Shipping, handling,
  tax and export-compliance lines -> is_component=false. order_no is TI's
  order number as printed, verbatim.
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


def _client(purpose='unknown'):
    import anthropic
    from app.ingest.claude_usage import TrackedClient
    return TrackedClient(anthropic.Anthropic(), purpose)


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


def _positive_int(value):
    try:
        n = int(value)
    except (ValueError, TypeError):
        return None
    return n if n > 0 else None


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

    # Payment receipts are dropped for every vendor since 2026-10-01
    # (PAYMENT_FALLBACK_VENDORS is empty): they never carried line items.
    payment_derived = bool(parsed.get('payment_derived'))
    if payment_derived and vendor not in PAYMENT_FALLBACK_VENDORS:
        return {'is_order': False, 'vendor': vendor, 'order_no': None,
                'event': None, 'items': [], 'total': None, 'tracking': None,
                'carrier': None, 'eta': None, 'payment_derived': True,
                'order_no_source': None, 'skipped_reason': 'payment receipt - not ingested since 2026-10-01'}

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
        'items_total': _positive_int(parsed.get('items_total')),
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

    response = _client('ingest.parse_order_email').messages.create(
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
of item titles (from Amazon/AliExpress/Adafruit/Mouser/DigiKey/Seeed/Rokland/Pololu/JLCPCB/eBay/\
Polycase/OnlineMetals/Yakima/Eletechsup/Cold & Colder/Texas Instruments \
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

    response = _client('ingest.infer_components').messages.create(
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
