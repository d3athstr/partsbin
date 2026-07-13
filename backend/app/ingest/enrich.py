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

If you cannot find a confident, directly-linkable asset or verifiable fact,
use null / omit the spec - never guess or fabricate."""

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
