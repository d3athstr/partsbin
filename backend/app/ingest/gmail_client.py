"""Gmail API client for the order-email ingestion pipeline.

OAuth tokens are persisted per-user (per Gmail account) in a JSON file at
PARTSBIN_GOOGLE_TOKENS (default /etc/partsbin/google-tokens.json, root/deploy
only). Runtime poll state (last poll, last error, re-auth debounce) lives in
a sibling JSON state file at PARTSBIN_INGEST_STATE.
"""
import base64
import json
import os
import tempfile
from datetime import datetime

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
GMAIL_QUERY = (
    # 'aliexpress' is deliberately bare: Don's AliExpress mail arrives via a
    # duck.com forwarding alias that rewrites the From address to
    # <sender>_at_<domain>_<hash>@duck.com, so from:aliexpress.com never matches.
    'from:(amazon.com OR aliexpress OR adafruit.com OR mouser.com OR digikey.com) '
    'newer_than:14d'
)


def tokens_path():
    """Path of the per-user Google token store"""
    return os.getenv('PARTSBIN_GOOGLE_TOKENS', '/etc/partsbin/google-tokens.json')


def state_path():
    """Path of the ingest runtime-state file"""
    return os.getenv('PARTSBIN_INGEST_STATE', '/etc/partsbin/ingest-state.json')


def get_accounts():
    """Gmail account names ingestion polls (e.g. don, deanna)"""
    return [a.strip() for a in os.getenv('INGEST_ACCOUNTS', 'don,deanna').split(',') if a.strip()]


def _load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_json(path, data):
    """Atomic write with restrictive permissions"""
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix='.tmp-')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def load_tokens():
    """Load the token store ({account: token dict})"""
    return _load_json(tokens_path())


def save_tokens(tokens):
    """Persist the token store"""
    _save_json(tokens_path(), tokens)


def load_state():
    """Load runtime state ({account: {last_poll, last_error, reauth_last_sent}})"""
    return _load_json(state_path())


def update_state(account, **fields):
    """Merge fields into an account's runtime state"""
    state = load_state()
    entry = state.get(account, {})
    entry.update(fields)
    state[account] = entry
    _save_json(state_path(), state)


# ==================== OAuth web flow ====================

def build_flow(state=None):
    """Build a google-auth-oauthlib web Flow from env-configured client creds"""
    from google_auth_oauthlib.flow import Flow

    client_id = os.getenv('GOOGLE_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
    redirect_uri = os.getenv('GOOGLE_REDIRECT_URI')
    if not client_id or not client_secret or not redirect_uri:
        raise RuntimeError(
            'GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI must be set'
        )

    client_config = {
        'web': {
            'client_id': client_id,
            'client_secret': client_secret,
            'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'redirect_uris': [redirect_uri],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=SCOPES, state=state)
    flow.redirect_uri = redirect_uri
    return flow


def get_auth_url(user):
    """Return (authorization_url, state, code_verifier) for a re-auth flow"""
    flow = build_flow()
    # No include_granted_scopes: the GCP client is shared with the voice
    # assistant, and merging its broader grants into this token makes Google
    # return extra scopes that oauthlib rejects as a scope change.
    auth_url, state = flow.authorization_url(
        access_type='offline',
        prompt='consent',  # force a refresh_token on every re-auth
    )
    # google-auth-oauthlib >= 1.0 auto-enables PKCE: the verifier generated
    # here must be handed back to the callback's Flow or Google rejects the
    # token exchange with "Missing code verifier".
    return auth_url, state, flow.code_verifier


def handle_callback(user, code, state=None, code_verifier=None):
    """Exchange the OAuth code, persist the token, return the account email"""
    # Tolerate Google returning a superset of the requested scopes (shared
    # client with prior grants); oauthlib otherwise raises "Scope has changed".
    os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
    flow = build_flow(state=state)
    flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    creds = flow.credentials

    email = None
    try:
        service = _build_service_from_creds(creds)
        profile = service.users().getProfile(userId='me').execute()
        email = profile.get('emailAddress')
    except Exception:
        pass  # token still usable; email is informational

    tokens = load_tokens()
    tokens[user] = _creds_to_dict(creds, email=email)
    save_tokens(tokens)
    update_state(user, last_error=None, reauth_last_sent=None)
    return email


def _creds_to_dict(creds, email=None):
    return {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri or 'https://oauth2.googleapis.com/token',
        'client_id': creds.client_id or os.getenv('GOOGLE_CLIENT_ID'),
        'client_secret': creds.client_secret or os.getenv('GOOGLE_CLIENT_SECRET'),
        'scopes': list(creds.scopes or SCOPES),
        'expiry': creds.expiry.isoformat() if creds.expiry else None,
        'email': email,
        'authorized_at': datetime.utcnow().isoformat(),
    }


def get_credentials(user, refresh=True):
    """Build google Credentials for an account, refreshing (and persisting) if needed.

    Returns None when no token is stored. Raises google.auth RefreshError when
    the grant is dead.
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    tokens = load_tokens()
    data = tokens.get(user)
    if not data:
        return None

    creds = Credentials(
        token=data.get('token'),
        refresh_token=data.get('refresh_token'),
        token_uri=data.get('token_uri', 'https://oauth2.googleapis.com/token'),
        client_id=data.get('client_id') or os.getenv('GOOGLE_CLIENT_ID'),
        client_secret=data.get('client_secret') or os.getenv('GOOGLE_CLIENT_SECRET'),
        scopes=data.get('scopes') or SCOPES,
    )

    if refresh and creds.refresh_token and not creds.valid:
        creds.refresh(Request())
        tokens[user] = _creds_to_dict(creds, email=data.get('email'))
        save_tokens(tokens)

    return creds


def force_refresh(user):
    """Keep-alive refresh regardless of expiry (used by the token monitor)"""
    from google.auth.transport.requests import Request

    tokens = load_tokens()
    data = tokens.get(user)
    if not data:
        return None

    creds = get_credentials(user, refresh=False)
    if not creds or not creds.refresh_token:
        return None
    creds.refresh(Request())
    tokens[user] = {**_creds_to_dict(creds, email=data.get('email'))}
    save_tokens(tokens)
    return creds


def token_status(user):
    """'ok' | 'dead' | 'missing' for an account's stored grant"""
    from google.auth.exceptions import RefreshError

    tokens = load_tokens()
    if user not in tokens:
        return 'missing'
    try:
        creds = get_credentials(user, refresh=True)
        return 'ok' if creds and (creds.valid or creds.refresh_token) else 'dead'
    except RefreshError:
        return 'dead'
    except Exception:
        return 'dead'


# ==================== Polling ====================

def _build_service_from_creds(creds):
    from googleapiclient.discovery import build
    return build('gmail', 'v1', credentials=creds, cache_discovery=False)


def _decode_body(data):
    """Decode a base64url Gmail body part"""
    if not data:
        return ''
    try:
        return base64.urlsafe_b64decode(data.encode()).decode('utf-8', errors='replace')
    except Exception:
        return ''


def _extract_bodies(payload):
    """Walk a Gmail message payload and return (text_body, html_body)"""
    text_parts = []
    html_parts = []

    def walk(part):
        mime = part.get('mimeType', '')
        body = part.get('body', {})
        if mime == 'text/plain':
            text_parts.append(_decode_body(body.get('data')))
        elif mime == 'text/html':
            html_parts.append(_decode_body(body.get('data')))
        for child in part.get('parts', []) or []:
            walk(child)

    walk(payload or {})
    return '\n'.join(p for p in text_parts if p), '\n'.join(p for p in html_parts if p)


def _header(headers, name):
    for h in headers or []:
        if h.get('name', '').lower() == name.lower():
            return h.get('value', '')
    return ''


def poll_account(user, known_ids):
    """Yield new order-candidate messages for an account.

    Runs the vendor Gmail query, skips ids already in known_ids
    (ProcessedMessage rows), fetches full messages and extracts bodies.

    Yields dicts: {id, subject, sender, date, body_text, body_html}
    """
    creds = get_credentials(user)
    if creds is None:
        raise RuntimeError(f'No Google token stored for account "{user}"')

    service = _build_service_from_creds(creds)

    message_ids = []
    page_token = None
    while True:
        resp = service.users().messages().list(
            userId='me', q=GMAIL_QUERY, pageToken=page_token, maxResults=100,
        ).execute()
        message_ids.extend(m['id'] for m in resp.get('messages', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break

    for mid in message_ids:
        if mid in known_ids:
            continue
        msg = service.users().messages().get(userId='me', id=mid, format='full').execute()
        payload = msg.get('payload', {})
        headers = payload.get('headers', [])
        body_text, body_html = _extract_bodies(payload)
        yield {
            'id': mid,
            'subject': _header(headers, 'Subject'),
            'sender': _header(headers, 'From'),
            'date': _header(headers, 'Date'),
            'body_text': body_text,
            'body_html': body_html,
        }
