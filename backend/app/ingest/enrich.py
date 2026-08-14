"""Web enrichment: find a product image + datasheet URL for a component.

Uses Claude's server-side web_search tool to locate a direct product-image URL
and (where meaningful) a manufacturer/distributor datasheet PDF, downloads the
image into the uploads tree, and stores the datasheet URL on the component.

Called in a background thread after auto-create, from the per-component API
endpoint, and from `flask enrich run` sweeps. Never overwrites assets a human
already set.
"""
import ipaddress
import json
import os
import socket
from urllib.parse import urlparse

import requests
from flask import current_app

from app import db
from app.models.component import Component
from app.ingest.claude_parser import MODEL, _client, _extract_json

SEARCH_SYSTEM = """You find reference assets for electronic components in an \
inventory system. Use web search to locate:

1. image_url - a DIRECT image file URL (.jpg/.jpeg/.png/.webp/.gif) showing the
   product itself. Prefer manufacturer or distributor product photos (Adafruit,
   SparkFun, DigiKey, Mouser, LCSC, Seeed, Espressif...) over marketplace
   collages with text overlays.
2. datasheet_url - a DIRECT PDF URL of the manufacturer datasheet, from the
   manufacturer or a major distributor. Use null when a datasheet is not
   meaningful (hookup wire, enclosures, assortment kits, tools).
3. metadata - manufacturer, manufacturer part number, a one-sentence
   description, and technical specs (short key/value strings) you can verify
   from what you find.
4. dimensions - the mechanical numbers a PCB or enclosure has to be drafted
   around, reported as specs keys. See DIMENSIONS below.

Respond with ONLY one JSON object, no prose, no markdown fences:
{"image_urls": [string, ...], "datasheet_url": string|null,
 "manufacturer": string|null, "mpn": string|null, "description": string|null,
 "specs": {}}

image_urls: up to 3 candidate direct-image URLs, best first (marketplace CDNs
often block hotlinking, so fallbacks matter). Empty list if none found.
Search results rarely contain direct image links - fetch a promising product
page (distributor or manufacturer) and take the product photo / og:image URL
from its markup.

Dev boards and modules ship in look-alike variants (flash/PSRAM codes like
N16R8 vs N8R2, USB-C vs micro-USB, WROOM module vs third-party carrier
board). Only report specs verified for the EXACT variant in the component
name; a family/module datasheet is acceptable but never one for a different
variant. When variant facts conflict across sources, omit them.

DIMENSIONS - millimetres, verified only, reported as specs keys.

KiCad already ships footprints for standard packages, so when the part is an
ordinary component in a named package (0805, SOT-23, DO-41, DO-201AD, TO-220,
DIP-8...) the package name IS the footprint: report `package` and stop. Spend
the effort on parts that have no standard footprint, where a board or a panel
cutout has to be drafted around the physical part:

  - modules / dev boards / breakouts (XIAO, buck converters, OLED panels,
    sensor boards): dim_body_mm "L x W", dim_height_mm, dim_hole_pitch_mm,
    dim_hole_dia_mm, dim_pin_pitch_mm, dim_pin_rows
  - radial and axial through-hole parts: dim_body_mm ("D x H" radial,
    "L x D" axial), dim_lead_spacing_mm, dim_lead_dia_mm
  - connectors and headers: dim_pitch_mm, dim_body_mm, dim_pin_dia_mm
  - enclosures, panels, batteries, antennas, mechanical parts:
    dim_body_mm "L x W x H", dim_mount_mm for a hole pattern

Report the dim_* keys even when the specs you were given already describe the
size in prose (form_factor, holder_dimensions, a sentence in the description).
The structured dim_* keys are what tooling reads; an existing prose mention
does NOT mean the dimensions are already recorded, and duplicating it as dim_*
is correct.

Values are bare numbers, no unit suffix ("17.8 x 21.0", not "17.8mm x 21mm").
Convert imperial to mm. Report a dimension ONLY from a datasheet, a
dimensional drawing, or an explicit listing specification - never scale one
off a product photo and never carry one over from a similar part. Unbranded
marketplace modules frequently publish no drawing at all; omitting the
dimensions is the correct answer there, and a wrong number is far worse than
a missing one because a board gets fabbed around it.

If you cannot find a confident, directly-linkable asset or verifiable fact,
use null / omit the spec - never guess or fabricate."""

PRICE_SYSTEM = """You find the current street price of an electronics part for \
an inventory system's budgeting.

Report the price of ONE unit in USD, as a hobbyist would pay it today from a
normal retail source (Adafruit, SparkFun, DigiKey, Mouser, LCSC, Seeed,
Amazon, AliExpress...). Not bulk/reel pricing, not distributor volume breaks,
unless the part is only ever sold that way.

Respond with ONLY one JSON object, no prose, no markdown fences:
{"unit_price": number|null, "currency": "USD", "source_url": string|null,
 "vendor": string|null, "pack_qty": number|null, "note": string|null}

unit_price: price for a SINGLE piece. When the listing you find is a multipack
(a 10-pack for $8.99), set pack_qty to the pack size and unit_price to the
per-piece price you derived from it (0.899).

Dev boards and modules ship in look-alike variants (flash/PSRAM codes like
N16R8 vs N8R2, USB-C vs micro-USB). Price the EXACT variant in the component
name; if you can only find a different variant, return unit_price null rather
than a price for the wrong part.

note: one short sentence on what you priced, e.g. "Adafruit single unit" or
"derived from a 20-pack on AliExpress".

If you cannot find a credible price for this specific part, return unit_price
null. Never guess or extrapolate a number."""

IMAGE_TYPES = {
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/webp': 'webp',
    'image/gif': 'gif',
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
HTTP_HEADERS = {'User-Agent': 'Mozilla/5.0 (PartsBin inventory; +https://parts.example.com)'}


def _url_is_safe(url):
    """https only, and the host must not resolve into private address space"""
    try:
        parsed = urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname:
            return False
        for info in socket.getaddrinfo(parsed.hostname, 443):
            if ipaddress.ip_address(info[4][0]).is_private:
                return False
        return True
    except Exception:
        return False


def find_assets(component):
    """Ask Claude (with web search) for image/datasheet URLs. Returns a dict."""
    query = ' '.join(filter(None, (component.manufacturer, component.mpn, component.name)))
    messages = [{
        'role': 'user',
        'content': (
            f'Component: {query}\n'
            f'Category: {component.category}\n'
            f'Specs: {json.dumps(component.specs or {})}'
        ),
    }]
    client = _client()
    try:
        # web_fetch lets Claude open a product page and lift the real photo URL
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=SEARCH_SYSTEM,
            tools=[
                {'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 3},
                {'type': 'web_fetch_20250910', 'name': 'web_fetch', 'max_uses': 3},
            ],
            betas=['web-fetch-2025-09-10'],
            messages=messages,
        )
    except Exception:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=SEARCH_SYSTEM,
            tools=[{'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 4}],
            messages=messages,
        )
    # With server tools the answer is the LAST text block
    text = ''
    for block in response.content:
        if block.type == 'text':
            text = block.text
    return _extract_json(text) or {}


def _download_image(component, url):
    """Download an image and save it under uploads/components/<id>/. Returns rel path or None."""
    if not _url_is_safe(url):
        return None
    resp = requests.get(url, headers=HTTP_HEADERS, timeout=20, stream=True)
    if resp.status_code != 200:
        return None
    ext = IMAGE_TYPES.get((resp.headers.get('Content-Type') or '').split(';')[0].strip())
    data = resp.raw.read(MAX_IMAGE_BYTES + 1, decode_content=True)
    if not data or len(data) > MAX_IMAGE_BYTES:
        return None
    if not ext:
        # CDNs often serve images as octet-stream; trust the magic bytes
        if data[:3] == b'\xff\xd8\xff':
            ext = 'jpg'
        elif data[:8] == b'\x89PNG\r\n\x1a\n':
            ext = 'png'
        elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            ext = 'webp'
        elif data[:6] in (b'GIF87a', b'GIF89a'):
            ext = 'gif'
    if not ext:
        return None

    rel_dir = os.path.join('components', str(component.id))
    abs_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    filename = f'web.{ext}'
    with open(os.path.join(abs_dir, filename), 'wb') as f:
        f.write(data)
    return os.path.join(rel_dir, filename)


def _datasheet_ok(url):
    """Cheap validation that the URL really serves a PDF"""
    if not _url_is_safe(url):
        return False
    try:
        resp = requests.get(url, headers=HTTP_HEADERS, timeout=15, stream=True)
        if resp.status_code != 200:
            return False
        if 'pdf' in (resp.headers.get('Content-Type') or '').lower():
            return True
        return resp.raw.read(5, decode_content=True).startswith(b'%PDF')
    except Exception:
        return False


def enrich_component(component_id, force=False):
    """Find + attach image/datasheet/metadata for one component.

    Only ever fills fields that are empty (and merges NEW spec keys) - existing
    values are never overwritten. With force=False the whole call is skipped
    when image + datasheet are already set (background/CLI economy); force=True
    (the manual Enrich button) always searches to fill remaining metadata.

    Returns a dict of what was newly attached.
    """
    empty = {'image': False, 'datasheet': False, 'manufacturer': False,
             'mpn': False, 'description': False, 'specs': 0}
    component = Component.query.get(component_id)
    if component is None:
        return empty
    if not force and component.image and component.datasheet_url:
        return empty

    assets = find_assets(component)
    result = dict(empty)

    image_candidates = assets.get('image_urls') or []
    if assets.get('image_url'):  # tolerate old single-URL shape
        image_candidates.append(assets['image_url'])
    if not component.image:
        for url in image_candidates[:3]:
            try:
                rel_path = _download_image(component, url)
            except Exception as e:
                current_app.logger.warning(f'enrich image {component_id}: {e}')
                rel_path = None
            if rel_path:
                component.image = rel_path
                result['image'] = True
                break

    if not component.datasheet_url and assets.get('datasheet_url'):
        if _datasheet_ok(assets['datasheet_url']):
            component.datasheet_url = assets['datasheet_url'][:500]
            result['datasheet'] = True

    for field, limit in (('manufacturer', 100), ('mpn', 100), ('description', None)):
        value = assets.get(field)
        if value and not getattr(component, field):
            value = str(value).strip()
            setattr(component, field, value[:limit] if limit else value)
            result[field] = True

    new_specs = assets.get('specs')
    if isinstance(new_specs, dict) and new_specs:
        specs = dict(component.specs or {})
        for key, value in new_specs.items():
            if key not in specs and isinstance(value, (str, int, float)) and str(value).strip():
                specs[key] = str(value).strip()[:100]
                result['specs'] += 1
        if result['specs']:
            component.specs = specs

    if any(result.values()):
        db.session.commit()
    return result


FROM_URL_SYSTEM = """You turn a product-page URL into a component definition \
for an electronics inventory. Fetch the URL (marketplaces may block fetches - \
then extract the product name from the URL slug and use web search instead). \
You are given the allowed category list.

Respond with ONLY one JSON object, no prose, no markdown fences:
{"name": string,               // concise canonical name, e.g. "0.1uF 50V Ceramic Capacitor (0805)"
 "category": string,           // MUST be one of the allowed categories
 "manufacturer": string|null,
 "mpn": string|null,
 "description": string|null,   // one short sentence
 "specs": {},                  // short key/value strings from the page
 "units_per_pack": integer,    // "100pcs" pack -> 100, else 1
 "image_urls": [string, ...],  // up to 3 direct product-image URLs, best first
 "datasheet_url": string|null} // direct PDF, manufacturer/distributor only

Strip marketing fluff from the name. Dev-board variant codes (N16R8 vs N8R2,
USB-C vs micro-USB) matter - keep them in the name and never mix variants.
Use null / [] rather than guessing."""


def component_from_url(source, categories):
    """Draft a component from a product URL or a pasted title (no DB writes)."""
    if source.startswith(('http://', 'https://')):
        task = f'Product URL: {source}'
    else:
        task = (f'Product title/description (no URL available - identify it '
                f'via web search): {source}')
    messages = [{
        'role': 'user',
        'content': f"Allowed categories: {', '.join(categories)}\n\n{task}",
    }]
    client = _client()
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=2500,
            system=FROM_URL_SYSTEM,
            tools=[
                {'type': 'web_fetch_20250910', 'name': 'web_fetch', 'max_uses': 3},
                {'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 3},
            ],
            betas=['web-fetch-2025-09-10'],
            messages=messages,
        )
    except Exception:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2500,
            system=FROM_URL_SYSTEM,
            tools=[{'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 4}],
            messages=messages,
        )
    text = ''
    for block in response.content:
        if block.type == 'text':
            text = block.text
    draft = _extract_json(text)
    if not draft or not (draft.get('name') or '').strip():
        return None
    units = draft.get('units_per_pack')
    draft['units_per_pack'] = units if isinstance(units, int) and units > 0 else 1
    if not isinstance(draft.get('specs'), dict):
        draft['specs'] = {}
    if not isinstance(draft.get('image_urls'), list):
        draft['image_urls'] = []
    return draft


def attach_image_from_urls(component, urls):
    """Download the first working candidate image for a component. Returns bool."""
    for url in (urls or [])[:3]:
        try:
            rel_path = _download_image(component, url)
        except Exception:
            rel_path = None
        if rel_path:
            component.image = rel_path
            return True
    return False


LOOKUP_SYSTEM = """You identify electronic components. Given an inventory \
component (possibly mis-identified) and the user's search hint, use web \
search (and fetch promising pages) to find CANDIDATE product identifications.

Respond with ONLY one JSON object, no prose, no markdown fences:
{"candidates": [
  {"title": string,             // the product as sold, concise
   "manufacturer": string|null,
   "mpn": string|null,
   "description": string|null,  // one short sentence
   "source_url": string|null,   // page you identified it from
   "image_urls": [string, ...], // up to 2 direct image URLs
   "datasheet_url": string|null,// direct PDF, manufacturer/distributor only
   "specs": {}}                 // short key/value strings
]}

Return up to 4 DISTINCT candidates, most likely first. Variants (N16R8 vs
N8R2, USB-C vs micro-USB) are different candidates - never blur them.
Use null / [] rather than guessing."""


def search_component_candidates(component, hint):
    """Web-search candidate identifications for a component. Returns a list."""
    prompt = (
        f'Inventory component: {component.name}\n'
        f'Category: {component.category}\n'
        f'Manufacturer: {component.manufacturer or "?"} | MPN: {component.mpn or "?"}\n'
        f'Specs: {json.dumps(component.specs or {})}\n\n'
        f'User search hint: {hint or component.name}'
    )
    client = _client()
    try:
        response = client.beta.messages.create(
            model=MODEL, max_tokens=3000, system=LOOKUP_SYSTEM,
            tools=[
                {'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 4},
                {'type': 'web_fetch_20250910', 'name': 'web_fetch', 'max_uses': 3},
            ],
            betas=['web-fetch-2025-09-10'],
            messages=[{'role': 'user', 'content': prompt}],
        )
    except Exception:
        response = client.messages.create(
            model=MODEL, max_tokens=3000, system=LOOKUP_SYSTEM,
            tools=[{'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 5}],
            messages=[{'role': 'user', 'content': prompt}],
        )
    text = ''
    for block in response.content:
        if block.type == 'text':
            text = block.text
    data = _extract_json(text) or {}
    out = []
    for cand in (data.get('candidates') or [])[:4]:
        if isinstance(cand, dict) and (cand.get('title') or '').strip():
            if not isinstance(cand.get('specs'), dict):
                cand['specs'] = {}
            if not isinstance(cand.get('image_urls'), list):
                cand['image_urls'] = []
            out.append(cand)
    return out


def apply_candidate(component, candidate):
    """Apply a user-chosen lookup candidate to a component.

    The user explicitly picked this identification, so image and datasheet
    REPLACE what's there; manufacturer/mpn/description fill only when empty
    (the name stays the user's to edit); new spec keys merge in.
    """
    result = {'image': False, 'datasheet': False, 'manufacturer': False,
              'mpn': False, 'description': False, 'specs': 0}

    if candidate.get('image_urls'):
        old = component.image
        component.image = None
        if attach_image_from_urls(component, candidate['image_urls']):
            result['image'] = True
        else:
            component.image = old

    ds = candidate.get('datasheet_url')
    if ds and _datasheet_ok(ds):
        component.datasheet_url = str(ds)[:500]
        result['datasheet'] = True

    for field, limit in (('manufacturer', 100), ('mpn', 100), ('description', None)):
        value = candidate.get(field)
        if value and not getattr(component, field):
            value = str(value).strip()
            setattr(component, field, value[:limit] if limit else value)
            result[field] = True

    new_specs = candidate.get('specs')
    if isinstance(new_specs, dict):
        specs = dict(component.specs or {})
        for key, value in new_specs.items():
            if key not in specs and isinstance(value, (str, int, float)) and str(value).strip():
                specs[str(key)[:60]] = str(value).strip()[:100]
                result['specs'] += 1
        if result['specs']:
            component.specs = specs

    if any(result.values()):
        db.session.commit()
    return result


def estimate_price(component):
    """Web-search a current unit price and store it as the ESTIMATE.

    Writes est_unit_cost with a source stamp so the number stays identifiable
    as a machine guess rather than a price someone verified. Never touches
    last_unit_cost - that is derived from what we really paid.

    Returns the estimate dict, or None when no credible price was found.
    The caller owns the commit.
    """
    from app.services.cost_service import set_estimated_cost

    query = ' '.join(filter(None, (component.manufacturer, component.mpn, component.name)))
    messages = [{
        'role': 'user',
        'content': (
            f'Component: {query}\n'
            f'Category: {component.category}\n'
            f'Specs: {json.dumps(component.specs or {})}\n'
            f'Description: {component.description or ""}'
        ),
    }]
    client = _client()
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=PRICE_SYSTEM,
            tools=[
                {'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 4},
                {'type': 'web_fetch_20250910', 'name': 'web_fetch', 'max_uses': 3},
            ],
            betas=['web-fetch-2025-09-10'],
            messages=messages,
        )
    except Exception:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=PRICE_SYSTEM,
            tools=[{'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 5}],
            messages=messages,
        )

    # With server tools the answer is the LAST text block
    text = ''
    for block in response.content:
        if block.type == 'text':
            text = block.text
    data = _extract_json(text) or {}

    price = data.get('unit_price')
    if price is None:
        return None
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None
    # A free part is not a price, and a five-figure hobby component is a
    # parsing accident (a whole-order total, or the wrong currency).
    if not 0 < price < 10000:
        current_app.logger.warning(
            f'Rejecting implausible price estimate {price} for component {component.id}'
        )
        return None

    source = data.get('source_url') or data.get('vendor') or 'web'
    set_estimated_cost(component, round(price, 4), source=f'claude:{source}')

    return {
        'unit_price': round(price, 4),
        'currency': data.get('currency') or 'USD',
        'source_url': data.get('source_url'),
        'vendor': data.get('vendor'),
        'pack_qty': data.get('pack_qty'),
        'note': data.get('note'),
    }
