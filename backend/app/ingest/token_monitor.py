"""Token keep-alive monitor.

Refreshes every stored Google grant on a timer (testing-mode tokens die ~7
days after consent). When a grant is dead, emails the affected user their
one-click re-auth link via the Shield SMTP relay, debounced to once per 24h
via the ingest state file - same pattern as voice-reauth-monitor.
"""
import os
from datetime import datetime, timedelta

from flask import current_app

from app.ingest import gmail_client
from app.services.email_service import send_reauth_email

REAUTH_DEBOUNCE = timedelta(hours=24)


def _reauth_url(account):
    site_url = os.getenv('SITE_URL', 'https://parts.example.com').rstrip('/')
    key = os.getenv('INGEST_KEY', '')
    return f'{site_url}/api/oauth/login/{account}?key={key}'


def _should_send(account):
    """Debounce re-auth emails to one per 24h per account"""
    state = gmail_client.load_state().get(account, {})
    last_sent = state.get('reauth_last_sent')
    if not last_sent:
        return True
    try:
        return datetime.utcnow() - datetime.fromisoformat(last_sent) > REAUTH_DEBOUNCE
    except ValueError:
        return True


def _notify_dead_grant(account, token):
    """Email the account owner their one-click re-auth link (debounced)"""
    to_email = token.get('email') or os.getenv(f'REAUTH_EMAIL_{account.upper()}')
    if not to_email:
        current_app.logger.warning(
            f'Token for "{account}" is dead but no email address is known - '
            f'set REAUTH_EMAIL_{account.upper()} or re-auth manually'
        )
        return False

    if not _should_send(account):
        current_app.logger.info(f'Re-auth email for "{account}" debounced (sent <24h ago)')
        return False

    sent = send_reauth_email(to_email, account, _reauth_url(account))
    if sent:
        gmail_client.update_state(account, reauth_last_sent=datetime.utcnow().isoformat())
        current_app.logger.info(f'Re-auth email sent to {to_email} for "{account}"')
    return sent


def run_token_monitor():
    """Refresh all tokens; notify owners of dead grants. Returns a summary."""
    from google.auth.exceptions import RefreshError

    tokens = gmail_client.load_tokens()
    summary = []

    for account in gmail_client.get_accounts():
        token = tokens.get(account)
        if token is None:
            summary.append({'account': account, 'status': 'missing'})
            continue

        try:
            creds = gmail_client.force_refresh(account)
            if creds is None:
                summary.append({'account': account, 'status': 'dead',
                                'detail': 'no refresh token stored'})
                _notify_dead_grant(account, token)
            else:
                gmail_client.update_state(account, last_error=None)
                summary.append({'account': account, 'status': 'ok'})
        except RefreshError as e:
            gmail_client.update_state(account, last_error=f'invalid_grant: {e}')
            summary.append({'account': account, 'status': 'dead', 'detail': str(e)})
            _notify_dead_grant(account, token)
        except Exception as e:
            current_app.logger.error(f'Token refresh failed for "{account}": {e}')
            summary.append({'account': account, 'status': 'error', 'detail': str(e)})

    return summary
