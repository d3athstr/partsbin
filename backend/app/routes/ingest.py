import os
from flask import Blueprint, request, session, redirect, current_app
from flask_login import login_required
from app.routes.admin import admin_required

ingest_bp = Blueprint('ingest', __name__)


@ingest_bp.route('/ingest/status', methods=['GET'])
@login_required
def get_ingest_status():
    """Per-Gmail-account ingestion status (token health, last poll, counts)"""
    try:
        from app.ingest.pipeline import ingest_status
        accounts = ingest_status()
        ingest_key = os.environ.get('INGEST_KEY', '')
        if ingest_key:
            for acct in accounts:
                acct['reauth_url'] = f"/api/oauth/login/{acct['account']}?key={ingest_key}"
        return {'accounts': accounts}, 200
    except Exception as e:
        current_app.logger.error(f'Failed to load ingest status: {e}')
        return {'error': 'Failed to load ingest status'}, 500


@ingest_bp.route('/ingest/run', methods=['POST'])
@admin_required
def run_ingest_now():
    """Manually trigger an ingestion run (admin)"""
    try:
        from app.ingest.pipeline import run_ingest
        summary = run_ingest()
        return {'message': 'Ingest run complete', 'summary': summary}, 200
    except Exception as e:
        current_app.logger.error(f'Ingest run failed: {e}')
        return {'error': f'Ingest run failed: {e}'}, 500


# ==================== Google OAuth (no session needed, gated by INGEST_KEY) ====================

@ingest_bp.route('/oauth/login/<user>', methods=['GET'])
def oauth_login(user):
    """Start the Google OAuth web flow for a Gmail account.

    Reached from the one-click re-auth email. Authenticated by the ingest key
    query param rather than a login session.
    """
    ingest_key = os.getenv('INGEST_KEY')
    if not ingest_key or request.args.get('key') != ingest_key:
        return {'error': 'Invalid or missing key'}, 403

    from app.ingest.gmail_client import get_accounts, get_auth_url

    if user not in get_accounts():
        return {'error': f'Unknown account "{user}"'}, 404

    try:
        auth_url, state = get_auth_url(user)
    except Exception as e:
        current_app.logger.error(f'Failed to build OAuth URL: {e}')
        return {'error': f'Failed to start OAuth flow: {e}'}, 500

    session['oauth_state'] = state
    session['oauth_user'] = user
    return redirect(auth_url)


@ingest_bp.route('/oauth/callback', methods=['GET'])
def oauth_callback():
    """Google OAuth callback - exchanges the code and stores the token"""
    error = request.args.get('error')
    if error:
        return {'error': f'Google returned an error: {error}'}, 400

    state = session.get('oauth_state')
    user = session.get('oauth_user')
    if not state or not user or request.args.get('state') != state:
        return {'error': 'OAuth state mismatch - restart the flow from your re-auth link'}, 400

    from app.ingest.gmail_client import handle_callback

    try:
        email = handle_callback(user, code=request.args.get('code'), state=state)
    except Exception as e:
        current_app.logger.error(f'OAuth callback failed: {e}')
        return {'error': f'Failed to complete OAuth flow: {e}'}, 500

    session.pop('oauth_state', None)
    session.pop('oauth_user', None)

    return (
        f'<html><body style="font-family: sans-serif; background: #0f1419; '
        f'color: #e8eaed; text-align: center; padding-top: 80px;">'
        f'<h2>PartsBin Gmail access authorized</h2>'
        f'<p>Account <strong>{user}</strong> ({email}) is connected. '
        f'You can close this tab.</p></body></html>'
    ), 200
