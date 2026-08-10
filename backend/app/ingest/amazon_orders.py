"""Recover Amazon order item detail from the authenticated order-details page.

Amazon redacted its order confirmation emails around 2026-07-15: the last real
product title PartsBin received by mail was 07-17, and everything since arrives
as "Ordered: 5 Electronics items" with no titles, prices, ASINs or product
links in either MIME part - and the matching "Shipped" mail is redacted too.
The legacy Order History Report CSV at /gp/b2b/reports is gone (bare 404, while
real pages redirect to sign-in), so the order-details page is the only source
of item detail left.

What the emails DO still carry reliably is the order number, the order date and
the grand total. So email ingestion keeps building a correct order *shell* and
this module fills in the items afterwards.

Parsing deliberately routes back through claude_parser.parse_order_email by
synthesising an order body from the scraped rows, rather than mapping the DOM
straight into OrderItems. That keeps ONE parsing brain: pack sizes
(units_per_item - "XIAO ESP32C6 3PCS Pack" is 3 units per line, and pricing it
per-piece depends on that), is_kit, and the is_component junk filter all behave
exactly as they do for email. A second implementation of those rules would be a
second set of ways to get stock wrong.

Session handling lives in scripts/amazon_session.py; this module only borrows a
browser context from it.
"""
import os
import re
import sys
import time
from datetime import date

from app import db
from app.ingest.claude_parser import parse_order_email
from app.ingest.matcher import is_placeholder_title
from app.models.order import Order, OrderItem

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'scripts')

ORDER_URL = 'https://www.amazon.com/gp/css/order-details?orderID={}'

# Throttle between order fetches. These are page loads against a real account
# from a datacenter IP; a burst is the fastest way to get the session
# challenged, and there is no hurry on a backfill.
FETCH_DELAY_SECONDS = float(os.getenv('AMAZON_FETCH_DELAY', '4'))

# Anchor on each item title and climb to the smallest ancestor that still
# describes ONE item but spans BOTH of Amazon's per-item grids.
#
# Quantity is the awkward part. [data-component="quantity"] exists but renders
# EMPTY; the visible count is an unclassed leaf <span> badge over the thumbnail
# in purchasedItemsLeftGrid, while the title and price live in the right grid.
# Reading the quantity component gives '' for every row, which silently
# defaults every line to qty 1 - an order of 2 packs then lands as 1, and the
# stock is wrong with nothing to indicate it. So: climb until the box holds the
# item image too, then take the first integer-only leaf span, preferring the
# left grid. Amazon omits the badge entirely for single items, so no badge
# legitimately means 1.
_EXTRACT_JS = """
() => {
  const txt = e => (e && e.innerText || '').trim();
  const intLeaf = root => {
    if (!root) return null;
    for (const e of root.querySelectorAll('span, div')) {
      if (e.children.length === 0 && /^\\d{1,3}$/.test((e.innerText || '').trim())) {
        return (e.innerText || '').trim();
      }
    }
    return null;
  };
  const out = [];
  document.querySelectorAll('[data-component="itemTitle"]').forEach(t => {
    let box = t;
    for (let i = 0; i < 12 && box.parentElement; i++) {
      const p = box.parentElement;
      if (p.querySelectorAll('[data-component="itemTitle"]').length > 1) break;
      box = p;
      if (box.querySelector('[data-component="itemImage"]') &&
          box.querySelector('[data-component="unitPrice"]')) break;
    }
    const a = t.querySelector('a[href*="/dp/"]') || box.querySelector('a[href*="/dp/"]');
    const m = a ? (a.getAttribute('href') || '').match(/\\/dp\\/([A-Z0-9]{10})/) : null;
    const left = box.querySelector('[data-component="purchasedItemsLeftGrid"]');
    out.push({
      title: txt(t),
      qty: intLeaf(left) || intLeaf(box.querySelector('[data-component="itemImage"]')) || '',
      price: txt(box.querySelector('[data-component="unitPrice"]')),
      seller: txt(box.querySelector('[data-component="orderedMerchant"]')),
      asin: m ? m[1] : null,
    });
  });
  return out;
}
"""


def _session_context(playwright, headless=True):
    """Browser context on the stored Amazon profile (scripts/amazon_session.py)."""
    if SCRIPTS_DIR not in sys.path:
        sys.path.insert(0, SCRIPTS_DIR)
    from amazon_session import _context, SIGNED_OUT_MARKERS  # noqa: F401
    return _context(playwright, headless=headless)


def _clean_qty(raw):
    """'2', 'Qty: 2' -> 2. Amazon omits it entirely for single items."""
    m = re.search(r'\d+', raw or '')
    return int(m.group()) if m else 1


def _clean_price(raw):
    """'$22.99\\n$22.99' -> 22.99. First money token wins (list price repeats)."""
    m = re.search(r'\$\s*([\d,]+\.\d{2})', raw or '')
    return float(m.group(1).replace(',', '')) if m else None


def fetch_order_rows(page, order_no):
    """Scrape one order-details page. Returns [] when the order shows no items.

    Raises RuntimeError if the session has gone stale, so a backfill stops
    instead of quietly recording dozens of empty orders.
    """
    page.goto(ORDER_URL.format(order_no), wait_until='domcontentloaded', timeout=60000)
    page.wait_for_timeout(3500)
    url = (page.url or '').lower()
    if 'ap/signin' in url or 'ax/claim' in url:
        raise RuntimeError('Amazon session expired - re-run: amazon_session.py login')
    rows = page.evaluate(_EXTRACT_JS)
    return [r for r in rows if (r.get('title') or '').strip()]


def rows_to_email_body(order, rows):
    """Render scraped rows as the plain-text order email Amazon no longer sends.

    Feeding this to the normal parser is what keeps pack-size and kit handling
    identical to the email path.
    """
    lines = [
        f'Order Confirmation - Order #{order.vendor_order_no}',
        f'Ordered on {(order.order_date or date.today()).isoformat()}',
        '',
        'Items in this order:',
    ]
    for r in rows:
        qty = _clean_qty(r.get('qty'))
        price = _clean_price(r.get('price'))
        seller = (r.get('seller') or '').replace('Sold by:', '').strip()
        bits = [f'  {qty} x {r["title"]}']
        if price is not None:
            bits.append(f'${price:.2f} each')
        if seller:
            bits.append(f'sold by {seller}')
        if r.get('asin'):
            bits.append(f'ASIN {r["asin"]}')
        lines.append(' - '.join(bits))
    if order.total is not None:
        lines += ['', f'Grand Total: ${float(order.total):.2f}']
    return '\n'.join(lines)


def needs_detail(order):
    """True when an order carries no usable item detail.

    Either it has no items at all, or every item is a redacted category
    placeholder ("Hardware item") - which is not item detail, it is a
    department name.
    """
    items = list(order.items)
    if not items:
        return True
    return all(is_placeholder_title(it.raw_title) for it in items)


def candidate_orders(limit=None, order_no=None, account=None, since=None,
                     include_ignored=False):
    """Amazon orders whose item detail is missing or redacted, oldest first.

    Returns (orders, skipped) so a caller can report what it declined to fetch
    rather than looking like it covered everything.

    'ignored' orders are skipped by default: those were auto-discarded because
    every item was non-inventory ("Pet item", "Apparel item"), and re-fetching
    ~89 of them costs a page load and a Claude call each to re-learn that dog
    food is not a component. The category noun is the one true thing a redacted
    title carries, so that judgement is sound - but a mixed-category order
    ("Arts & Crafts and Office items") could in principle hide a real part,
    which is why --include-ignored exists.
    """
    q = Order.query.filter(Order.vendor == 'amazon')
    if order_no:
        q = q.filter(Order.vendor_order_no == order_no)
    if account:
        q = q.filter(Order.gmail_account == account)
    if since:
        q = q.filter(Order.order_date >= since)
    orders = [o for o in q.order_by(Order.order_date.asc()).all() if needs_detail(o)]

    skipped = []
    if not include_ignored and not order_no:
        skipped = [o for o in orders if o.status == 'ignored']
        orders = [o for o in orders if o.status != 'ignored']
    capped = orders[:limit] if limit else orders
    if limit and len(orders) > limit:
        skipped += orders[limit:]
    return capped, skipped


def _drop_placeholder_items(order):
    """Remove redacted placeholder rows, but never one that moved stock.

    A placeholder that already landed stock is a data-integrity problem needing
    a human decision (it happened once, on 2026-07-22), not something to delete
    silently underneath the ledger.
    """
    from app.models.component import StockTransaction

    dropped, kept = 0, 0
    for it in list(order.items):
        if not is_placeholder_title(it.raw_title):
            continue
        if StockTransaction.query.filter_by(order_item_id=it.id).first():
            kept += 1
            continue
        db.session.delete(it)
        dropped += 1
    return dropped, kept


def import_order_details(order, rows):
    """Replace an order's redacted items with the real ones. Returns a summary."""
    from app.ingest.pipeline import create_order_items

    body = rows_to_email_body(order, rows)
    parsed = parse_order_email(
        f'Order #{order.vendor_order_no} confirmed',
        'order-details@amazon.com',
        body,
    )
    if not parsed or not parsed.get('items'):
        return {'order': order.vendor_order_no, 'status': 'no items parsed',
                'scraped': len(rows), 'created': 0}

    dropped, kept = _drop_placeholder_items(order)
    db.session.flush()
    created = create_order_items(order, parsed['items'], event='ordered',
                                 account=order.gmail_account)
    if order.total is None and parsed.get('total') is not None:
        order.total = parsed['total']
    return {'order': order.vendor_order_no, 'status': 'ok', 'scraped': len(rows),
            'created': created, 'placeholders_dropped': dropped,
            'placeholders_kept_with_stock': kept}


def backfill(limit=None, order_no=None, account=None, since=None,
             include_ignored=False, dry_run=False, log=print):
    """Fetch and import item detail for every order missing it."""
    from playwright.sync_api import sync_playwright

    orders, skipped = candidate_orders(limit=limit, order_no=order_no,
                                       account=account, since=since,
                                       include_ignored=include_ignored)
    if skipped:
        # Never let a bounded run read as full coverage.
        log(f'skipping {len(skipped)} order(s): '
            f'{len([o for o in skipped if o.status == "ignored"])} auto-ignored as '
            f'non-inventory (--include-ignored to fetch them), '
            f'{len([o for o in skipped if o.status != "ignored"])} beyond --limit')
    if not orders:
        log('nothing to do: no Amazon orders missing item detail')
        return []
    log(f'{len(orders)} order(s) need item detail'
        f'{" (dry run)" if dry_run else ""}')

    results = []
    with sync_playwright() as pw:
        ctx = _session_context(pw, headless=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            for i, order in enumerate(orders):
                try:
                    rows = fetch_order_rows(page, order.vendor_order_no)
                except RuntimeError as e:
                    log(f'! {e}')
                    break
                except Exception as e:
                    log(f'! {order.vendor_order_no}: fetch failed: {e}')
                    results.append({'order': order.vendor_order_no,
                                    'status': f'fetch failed: {e}'})
                    continue
                if not rows:
                    # The page renders (title "Order Details", ~7.5KB, no error
                    # text) but carries no items at all. Seen on 6 of the first
                    # 9 backfilled orders, every one of them a non-electronics
                    # category - Apparel, Pet, Beauty, Arts & Crafts, Drugstore.
                    # Most likely an Amazon Household profile thing: the
                    # confirmation mail reaches the shared inbox, but the order
                    # detail is only visible to the profile that placed it.
                    # Report it; never invent items to fill the gap.
                    log(f'  {order.vendor_order_no}: page has no items '
                        f'(likely another Household profile, or archived)')
                    results.append({'order': order.vendor_order_no, 'status': 'no items on page'})
                    continue
                if dry_run:
                    log(f'  {order.vendor_order_no}: would import {len(rows)} item(s)')
                    for r in rows:
                        log(f'      {_clean_qty(r.get("qty"))} x {r["title"][:72]}')
                    results.append({'order': order.vendor_order_no, 'status': 'dry-run',
                                    'scraped': len(rows)})
                else:
                    res = import_order_details(order, rows)
                    db.session.commit()
                    log(f'  {order.vendor_order_no}: {res["created"]} item(s) imported')
                    results.append(res)
                if i < len(orders) - 1:
                    time.sleep(FETCH_DELAY_SECONDS)
        finally:
            ctx.close()
    return results
