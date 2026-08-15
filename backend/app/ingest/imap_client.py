"""IMAP ingestion source — the dedicated PartsBin mailbox.

WHY THIS EXISTS
The original ingestion path polls Don's and DeAnna's personal Gmail through the
Gmail API. That path has three structural problems this one removes:

  1. The OAuth app is in Testing publishing status, so Google expires the
     refresh token about every 7 days. When it dies, orders simply stop
     appearing — silently. It cost two days of ingestion on 2026-08-09, and
     DeAnna's consent has been broken since June.
  2. `gmail_client.GMAIL_QUERY_BASE` hardcodes which SENDER DOMAINS are even
     fetched. Adding a vendor is nine separate edits and every miss degrades
     silently. A dedicated mailbox inverts that: anything delivered here is a
     candidate, so there is no allowlist to forget.
  3. Vendors bound to other addresses (Seeed and eBay on Outlook) could only
     arrive as hand-forwards, which is why payment-receipt fallbacks and
     per-vendor special cases accumulated.

This module deliberately mirrors `gmail_client.poll_account()` — same generator
contract, same dict shape — so `pipeline.run_ingest()` treats a mailbox exactly
like a Gmail account and none of the parsing, matching or dedupe logic changes.

TLS: we connect to mail.empire12.net by HOSTNAME, not by IP, because the
Dovecot certificate is valid for the name and fails verification for the
address. Certificate verification stays ON — do not "fix" a connection error by
disabling it.
"""

import email
import hashlib
import imaplib
import json
import os
import re
import ssl
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime

# Connect by name so the certificate verifies; see module docstring.
DEFAULT_HOST = 'mail.empire12.net'
DEFAULT_PORT = 993
DEFAULT_USER = 'partsbin'
DEFAULT_MAILBOX = 'INBOX'

# Which PartsBin user owns orders found here. Orders are scoped per user by
# `Order.gmail_account` (`_visible_orders()`), so a mailbox that ingested under
# its own name would produce orders NOBODY can see — the routes 404 across
# users. Attributing to 'don' is what makes these orders visible in the UI and
# over MCP (the mcp-service account is mapped to 'don' for the same reason).
DEFAULT_ACCOUNT = 'don'

# Per-message attribution. Don and DeAnna forward into the SAME mailbox, so the
# owning account cannot come from the mailbox — it has to come from the message.
#
# Verified against a real Gmail auto-forward on 2026-08-12:
#     X-Forwarded-To:  partsbin@empire12.net
#     X-Forwarded-For: don.g.jackson@gmail.com partsbin@empire12.net
#     Delivered-To:    don.g.jackson@gmail.com
#
# The FIRST address in X-Forwarded-For is the mailbox that forwarded, which is
# exactly the signal we need. Manual "Fwd:" messages carry no such header, so we
# fall back to Delivered-To and then From.
#
# This matters more than it looks: orders are scoped per user, so mis-attributing
# a message hides the order from the person who placed it (cross-user reads 404).
DEFAULT_ACCOUNT_MAP = {
    'don.g.jackson@gmail.com': 'don',
    'don.jackson@outlook.com': 'don',
    'lurkakitty@gmail.com': 'deanna',
}


def account_map():
    """Forwarding address -> PartsBin account. Override with JSON in env."""
    raw = os.getenv('PARTSBIN_IMAP_ACCOUNT_MAP')
    if raw:
        try:
            return {k.lower(): v for k, v in json.loads(raw).items()}
        except Exception:
            pass
    return dict(DEFAULT_ACCOUNT_MAP)


def _addresses(value):
    """All e-mail addresses in a header value, lowercased.

    X-Forwarded-For is space-separated rather than comma-separated, which
    getaddresses does not split, so fall back to a plain scan.
    """
    if not value:
        return []
    found = [a.lower() for _n, a in getaddresses([value]) if a and '@' in a]
    if not found:
        found = [m.lower() for m in re.findall(r'[\w.+-]+@[\w.-]+\.\w+', value)]
    return found


def attribute_account(msg, default=None):
    """Which PartsBin account owns this message.

    Checks the forwarding headers in order of reliability, ignoring the mailbox
    address itself (every message here is addressed to it, so it carries no
    information). Falls back to the configured default rather than guessing.
    """
    cfg = imap_config()
    mailbox_prefix = (cfg['user'] or '').lower() + '@'
    mapping = account_map()
    default = default or cfg['account']

    for header in ('X-Forwarded-For', 'Delivered-To', 'X-Original-To', 'From'):
        for value in msg.get_all(header) or []:
            for addr in _addresses(value):
                if addr.startswith(mailbox_prefix):
                    continue  # the mailbox itself is on every message; no signal
                if addr in mapping:
                    return mapping[addr]
    return default


def imap_config():
    """Connection settings, env-overridable.

    Password comes from the environment (populated from Vault
    secret/empire12/partsbin/mailbox) — never hardcode it here.
    """
    return {
        'host': os.getenv('PARTSBIN_IMAP_HOST', DEFAULT_HOST),
        'port': int(os.getenv('PARTSBIN_IMAP_PORT', DEFAULT_PORT)),
        'user': os.getenv('PARTSBIN_IMAP_USER', DEFAULT_USER),
        'password': os.getenv('PARTSBIN_IMAP_PASSWORD', ''),
        'mailbox': os.getenv('PARTSBIN_IMAP_MAILBOX', DEFAULT_MAILBOX),
        'account': os.getenv('PARTSBIN_IMAP_ACCOUNT', DEFAULT_ACCOUNT),
    }


def is_enabled():
    """True when a mailbox password is configured.

    Absent config disables the source rather than raising, so a deployment that
    has not been given the credential yet keeps polling Gmail instead of
    failing the whole ingest run.
    """
    return bool(imap_config()['password'])


def _connect():
    cfg = imap_config()
    if not cfg['password']:
        raise RuntimeError(
            'PARTSBIN_IMAP_PASSWORD is not set — mailbox ingestion is disabled'
        )
    # Verified TLS. The cert is valid for the hostname; connecting by IP will
    # fail hostname verification. Fix DNS, not the SSL context.
    ctx = ssl.create_default_context()
    conn = imaplib.IMAP4_SSL(cfg['host'], cfg['port'], ssl_context=ctx)
    conn.login(cfg['user'], cfg['password'])
    return conn, cfg


def _decode(value):
    """Decode an RFC 2047 header to plain text, tolerating malformed input."""
    if not value:
        return ''
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


def _extract_bodies(msg):
    """Return (text, html) from a parsed message.

    Mirrors gmail_client._extract_bodies. Attachments are skipped — a PDF
    invoice is not the body, and passing its bytes to the parser is noise.
    """
    text_parts, html_parts = [], []

    def _payload(part):
        try:
            raw = part.get_payload(decode=True)
        except Exception:
            return ''
        if raw is None:
            return ''
        charset = part.get_content_charset() or 'utf-8'
        try:
            return raw.decode(charset, errors='replace')
        except (LookupError, UnicodeDecodeError):
            return raw.decode('utf-8', errors='replace')

    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == 'multipart':
                continue
            disposition = str(part.get('Content-Disposition') or '')
            if 'attachment' in disposition.lower():
                continue
            ctype = part.get_content_type()
            if ctype == 'text/plain':
                text_parts.append(_payload(part))
            elif ctype == 'text/html':
                html_parts.append(_payload(part))
    else:
        if msg.get_content_type() == 'text/html':
            html_parts.append(_payload(msg))
        else:
            text_parts.append(_payload(msg))

    return '\n'.join(p for p in text_parts if p), '\n'.join(p for p in html_parts if p)


def _message_id(msg, raw):
    """Stable, portable id for ProcessedMessage.

    Uses the RFC822 Message-ID, which survives the message being moved between
    folders or the mailbox being rebuilt — unlike an IMAP UID, which does not.
    Falls back to a content hash when a sender omits the header, so a malformed
    message can still be recorded as processed and never reprocessed forever.
    """
    mid = (msg.get('Message-ID') or '').strip()
    if mid:
        return mid[:100]
    return 'sha256:' + hashlib.sha256(raw).hexdigest()[:80]


def _sort_key(entry):
    """Oldest-first ordering.

    The pipeline depends on this: an order's 'Ordered' email must be processed
    before its 'Shipped'/'Delivered' ones, because status ranking and the
    combined-shipment duplicate guard both assume that order. gmail_client
    reverses Gmail's newest-first listing for the same reason.
    """
    return entry[0] or 0


def poll_account(account, known_ids):
    """Yield new order-candidate messages from the mailbox.

    Same contract as gmail_client.poll_account: yields dicts of
    {id, subject, sender, date, body_text, body_html}, skipping ids already
    recorded in ProcessedMessage.

    NOTE there is deliberately NO sender allowlist here. Everything delivered to
    this mailbox is a candidate — that is the entire point of a dedicated
    address, and it is what removes the nine-gate vendor-onboarding problem.
    The parser still classifies non-orders, and the pipeline's pharmacy/delay
    guards still apply upstream of Claude.
    """
    conn, cfg = _connect()
    try:
        status, _ = conn.select(cfg['mailbox'], readonly=True)
        if status != 'OK':
            raise RuntimeError(f'cannot select mailbox {cfg["mailbox"]}')

        status, data = conn.search(None, 'ALL')
        if status != 'OK':
            raise RuntimeError('IMAP search failed')

        uids = data[0].split()
        # Read everything and dedupe on ProcessedMessage rather than consuming
        # \Seen flags: flag-based reading loses a message permanently if a run
        # dies mid-way, and readonly=True means we never mutate the mailbox.
        entries = []
        for uid in uids:
            status, msg_data = conn.fetch(uid, '(RFC822)')
            if status != 'OK' or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            mid = _message_id(msg, raw)
            if mid in known_ids:
                continue
            try:
                ts = parsedate_to_datetime(msg.get('Date')).timestamp()
            except Exception:
                ts = 0
            entries.append((ts, mid, msg))

        entries.sort(key=_sort_key)

        for _ts, mid, msg in entries:
            body_text, body_html = _extract_bodies(msg)
            yield {
                'id': mid,
                'subject': _decode(msg.get('Subject')),
                'sender': _decode(msg.get('From')),
                'date': msg.get('Date'),
                'body_text': body_text,
                'body_html': body_html,
                # Per-message, because Don and DeAnna share this mailbox.
                'account': attribute_account(msg, default=account),
            }
    finally:
        try:
            conn.close()
        except Exception:
            pass
        try:
            conn.logout()
        except Exception:
            pass


def status():
    """Health of the mailbox source, for `flask ingest status`."""
    cfg = imap_config()
    info = {
        'source': 'imap',
        'host': cfg['host'],
        'user': cfg['user'],
        'mailbox': cfg['mailbox'],
        'account': cfg['account'],
        'enabled': is_enabled(),
    }
    if not is_enabled():
        info['state'] = 'disabled (no PARTSBIN_IMAP_PASSWORD)'
        return info
    try:
        conn, _ = _connect()
        try:
            st, data = conn.select(cfg['mailbox'], readonly=True)
            info['state'] = 'ok' if st == 'OK' else 'select failed'
            info['messages'] = int(data[0]) if st == 'OK' and data and data[0] else 0
        finally:
            try:
                conn.close()
            except Exception:
                pass
            conn.logout()
    except Exception as e:
        info['state'] = 'error'
        info['error'] = str(e)
    return info
