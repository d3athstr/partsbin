from flask import Blueprint, request, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models.user import User
from app.models.passkey import PasskeyCredential
from app.models.invitation import InvitationCode
import secrets
import os
from datetime import datetime
import pyotp
import qrcode
import io
import base64
from cryptography.fernet import Fernet

# WebAuthn imports
from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    options_to_json,
)
from webauthn.helpers import bytes_to_base64url, base64url_to_bytes
from webauthn.helpers.cose import COSEAlgorithmIdentifier

# Match GarmentGallery2's (py_webauthn 2.7) algorithm list and order — the
# 3.x default (EdDSA first, 3 algs) hung Safari's passkey prompt for Don.
GG_PUB_KEY_ALGS = [
    COSEAlgorithmIdentifier.ECDSA_SHA_256,
    COSEAlgorithmIdentifier.EDDSA,
    COSEAlgorithmIdentifier.ECDSA_SHA_512,
    COSEAlgorithmIdentifier.RSASSA_PSS_SHA_256,
    COSEAlgorithmIdentifier.RSASSA_PSS_SHA_384,
    COSEAlgorithmIdentifier.RSASSA_PSS_SHA_512,
    COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,
    COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_384,
    COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_512,
]
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    UserVerificationRequirement,
    ResidentKeyRequirement,
    PublicKeyCredentialDescriptor,
    AuthenticatorTransport,
)

auth_bp = Blueprint('auth', __name__)


# ==================== Helper Functions ====================

def get_cipher_suite():
    """Get Fernet cipher suite for TOTP encryption"""
    key = os.getenv('ENCRYPTION_KEY')
    if key:
        try:
            return Fernet(key.encode())
        except Exception as e:
            current_app.logger.error(f'Failed to create cipher suite: {e}')
            return None
    return None


def get_rp_id():
    """Get Relying Party ID from config or derive from server name"""
    return os.getenv('WEBAUTHN_RP_ID', 'localhost')


def get_rp_name():
    """Get Relying Party name"""
    return os.getenv('WEBAUTHN_RP_NAME', 'PartsBin')


def get_origin():
    """Get expected origin for WebAuthn verification"""
    origin = os.getenv('WEBAUTHN_ORIGIN')
    if origin:
        return origin
    rp_id = get_rp_id()
    if rp_id == 'localhost':
        return 'http://localhost:5173'
    return f'https://{rp_id}'


# ==================== Basic Auth ====================

@auth_bp.route('/register', methods=['POST'])
def register():
    """Register a new user (requires valid invitation code)"""
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')
    invitation_code = (data.get('invite_code') or data.get('invitation_code') or '').strip()

    # Validation
    if not username or not email or not password:
        return {'error': 'Username, email, and password are required'}, 400

    if not invitation_code:
        return {'error': 'Invitation code is required'}, 400

    if len(username) < 3:
        return {'error': 'Username must be at least 3 characters'}, 400

    if len(password) < 8:
        return {'error': 'Password must be at least 8 characters'}, 400

    # Validate invitation code
    invitation = InvitationCode.query.filter_by(code=invitation_code).first()
    if not invitation:
        return {'error': 'Invalid invitation code'}, 400

    if not invitation.is_valid:
        return {'error': 'Invitation code has expired or has been used'}, 400

    # Check if user already exists
    if User.query.filter_by(username=username).first():
        return {'error': 'Username already exists'}, 409

    if User.query.filter_by(email=email).first():
        return {'error': 'Email already exists'}, 409

    # Create user (the very first user bootstraps as approved admin)
    user = User(username=username, email=email)
    user.set_password(password)
    if User.query.count() == 0:
        user.is_admin = True
        user.is_approved = True

    try:
        db.session.add(user)
        db.session.flush()  # Get user.id before committing

        # Mark invitation as used
        invitation.use(user)

        db.session.commit()
        return {'message': 'User created successfully', 'user': user.to_dict()}, 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to create user: {e}')
        return {'error': 'Failed to create user'}, 500


@auth_bp.route('/login', methods=['POST'])
def login():
    """Login user with username/password - may require TOTP verification"""
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return {'error': 'Username and password are required'}, 400

    # Find user
    user = User.query.filter_by(username=username).first()

    if not user or not user.check_password(password):
        return {'error': 'Invalid username or password'}, 401

    # Check if user is approved
    if not user.is_approved:
        return {'error': 'Your account is pending approval. Please contact an administrator.'}, 403

    # Check if TOTP is enabled
    if user.totp_enabled:
        # Generate temp token for TOTP verification
        temp_token = secrets.token_urlsafe(32)
        session['totp_temp_token'] = temp_token
        session['totp_user_id'] = user.id
        session.permanent = False  # Session expires when browser closes

        return {
            'totp_required': True,
            'temp_token': temp_token
        }, 200

    # No TOTP - login directly
    login_user(user, remember=True)
    return {'user': user.to_dict()}, 200


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    """Logout user"""
    logout_user()
    return {'message': 'Logged out successfully'}, 200


@auth_bp.route('/me', methods=['GET'])
@login_required
def get_current_user():
    """Get current user information"""
    return {'user': current_user.to_dict()}, 200


@auth_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    """Change the current user's password"""
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')

    if not current_user.check_password(current_password):
        return {'error': 'Current password is incorrect'}, 401

    if len(new_password) < 8:
        return {'error': 'New password must be at least 8 characters'}, 400

    current_user.set_password(new_password)
    db.session.commit()

    return {'message': 'Password changed successfully'}, 200


# ==================== TOTP Authentication ====================

@auth_bp.route('/verify-totp', methods=['POST'])
def verify_totp():
    """Verify TOTP code and complete login"""
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    temp_token = data.get('temp_token', '')
    code = data.get('code', '')

    if not temp_token or not code:
        return {'error': 'Temp token and code are required'}, 400

    # Validate temp token from session
    stored_token = session.get('totp_temp_token')
    user_id = session.get('totp_user_id')

    if not stored_token or stored_token != temp_token:
        return {'error': 'Invalid or expired session'}, 401

    # Get user
    user = User.query.get(user_id)
    if not user:
        return {'error': 'User not found'}, 404

    # Get cipher suite
    cipher_suite = get_cipher_suite()
    if not cipher_suite:
        return {'error': 'TOTP encryption not configured'}, 500

    # Get TOTP secret and verify
    secret = user.get_totp_secret(cipher_suite)
    if not secret:
        return {'error': 'TOTP not configured for this user'}, 500

    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        return {'error': 'Invalid TOTP code'}, 401

    # Clear session tokens
    session.pop('totp_temp_token', None)
    session.pop('totp_user_id', None)

    # Login user
    login_user(user, remember=True)
    return {'user': user.to_dict()}, 200


@auth_bp.route('/setup-totp', methods=['GET'])
@login_required
def setup_totp():
    """Generate TOTP secret and QR code for setup"""
    if current_user.totp_enabled:
        return {'error': 'TOTP is already enabled'}, 400

    # Generate new TOTP secret
    secret = pyotp.random_base32()

    # Store temporarily in session
    session['totp_setup_secret'] = secret

    # Generate provisioning URI
    issuer = current_app.config.get('TOTP_ISSUER_NAME', 'PartsBin')
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(
        name=current_user.email,
        issuer_name=issuer
    )

    # Generate QR code
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    qr_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

    return {
        'qr_code': qr_base64,
        'secret': secret
    }, 200


@auth_bp.route('/enable-totp', methods=['POST'])
@login_required
def enable_totp():
    """Enable TOTP after verifying setup code"""
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    code = data.get('code', '')

    if not code:
        return {'error': 'Verification code is required'}, 400

    # Get secret from session
    secret = session.get('totp_setup_secret')
    if not secret:
        return {'error': 'No TOTP setup in progress'}, 400

    # Verify the code
    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        return {'error': 'Invalid verification code'}, 401

    # Get cipher suite
    cipher_suite = get_cipher_suite()
    if not cipher_suite:
        return {'error': 'TOTP encryption not configured'}, 500

    # Save encrypted secret to database
    try:
        current_user.set_totp_secret(secret, cipher_suite)
        current_user.totp_enabled = True
        db.session.commit()

        # Clear session
        session.pop('totp_setup_secret', None)

        return {'message': 'TOTP enabled successfully'}, 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to enable TOTP: {e}')
        return {'error': 'Failed to enable TOTP'}, 500


@auth_bp.route('/disable-totp', methods=['POST'])
@login_required
def disable_totp():
    """Disable TOTP (requires password verification)"""
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    password = data.get('password', '')

    if not password:
        return {'error': 'Password is required'}, 400

    # Verify password
    if not current_user.check_password(password):
        return {'error': 'Invalid password'}, 401

    if not current_user.totp_enabled:
        return {'error': 'TOTP is not enabled'}, 400

    # Disable TOTP
    try:
        current_user.totp_enabled = False
        current_user.totp_secret_encrypted = None
        db.session.commit()

        return {'message': 'TOTP disabled successfully'}, 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to disable TOTP: {e}')
        return {'error': 'Failed to disable TOTP'}, 500


# ==================== Passkey Registration ====================

@auth_bp.route('/passkey/register/options', methods=['GET'])
@login_required
def passkey_register_options():
    """Generate WebAuthn registration options"""
    # Get existing credentials to exclude
    existing_credentials = []
    for passkey in current_user.passkeys:
        existing_credentials.append(
            PublicKeyCredentialDescriptor(id=passkey.credential_id)
        )

    # Generate user ID (use existing or create new)
    user_id = str(current_user.id).encode('utf-8')

    options = generate_registration_options(
        rp_id=get_rp_id(),
        rp_name=get_rp_name(),
        user_id=user_id,
        user_name=current_user.username,
        user_display_name=current_user.username,
        exclude_credentials=existing_credentials,
        supported_pub_key_algs=GG_PUB_KEY_ALGS,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )

    # Store challenge in session
    session['passkey_register_challenge'] = bytes_to_base64url(options.challenge)

    return options_to_json(options), 200


@auth_bp.route('/passkey/register/verify', methods=['POST'])
@login_required
def passkey_register_verify():
    """Verify and store WebAuthn registration response"""
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    # Get stored challenge
    expected_challenge = session.get('passkey_register_challenge')
    if not expected_challenge:
        return {'error': 'No registration in progress'}, 400

    passkey_name = data.get('name', 'My Passkey')
    credential_data = data.get('credential')

    if not credential_data:
        return {'error': 'Credential data is required'}, 400

    try:
        # Verify the registration response
        verification = verify_registration_response(
            credential=credential_data,
            expected_challenge=base64url_to_bytes(expected_challenge),
            expected_rp_id=get_rp_id(),
            expected_origin=get_origin(),
        )

        # Check if credential ID already exists
        existing = PasskeyCredential.query.filter_by(
            credential_id=verification.credential_id
        ).first()
        if existing:
            return {'error': 'This passkey is already registered'}, 409

        # Get transports if provided
        transports = None
        if 'transports' in credential_data.get('response', {}):
            transports = ','.join(credential_data['response']['transports'])

        # Store credential
        passkey = PasskeyCredential(
            user_id=current_user.id,
            credential_id=verification.credential_id,
            public_key=verification.credential_public_key,
            sign_count=verification.sign_count,
            name=passkey_name,
            transports=transports,
        )

        db.session.add(passkey)
        db.session.commit()

        # Clear session
        session.pop('passkey_register_challenge', None)

        return {
            'message': 'Passkey registered successfully',
            'passkey': passkey.to_dict()
        }, 201

    except Exception as e:
        current_app.logger.error(f'Passkey registration failed: {e}')
        return {'error': f'Registration verification failed: {str(e)}'}, 400


# ==================== Passkey Authentication ====================

@auth_bp.route('/passkey/auth/options', methods=['POST'])
def passkey_auth_options():
    """Generate WebAuthn authentication options"""
    data = request.get_json() or {}
    username = data.get('username', '').strip()

    # If username provided, get credentials for that user
    allowed_credentials = []
    if username:
        user = User.query.filter_by(username=username).first()
        if user:
            for passkey in user.passkeys:
                transports = None
                if passkey.transports:
                    transports = [
                        AuthenticatorTransport(t)
                        for t in passkey.transports.split(',')
                        if t in ['usb', 'nfc', 'ble', 'internal', 'hybrid']
                    ]
                allowed_credentials.append(
                    PublicKeyCredentialDescriptor(
                        id=passkey.credential_id,
                        transports=transports,
                    )
                )
            session['passkey_auth_user_id'] = user.id

    options = generate_authentication_options(
        rp_id=get_rp_id(),
        allow_credentials=allowed_credentials if allowed_credentials else None,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    # Store challenge in session
    session['passkey_auth_challenge'] = bytes_to_base64url(options.challenge)

    return options_to_json(options), 200


@auth_bp.route('/passkey/auth/verify', methods=['POST'])
def passkey_auth_verify():
    """Verify WebAuthn authentication response and login"""
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    # Get stored challenge
    expected_challenge = session.get('passkey_auth_challenge')
    if not expected_challenge:
        return {'error': 'No authentication in progress'}, 400

    credential_data = data.get('credential')
    if not credential_data:
        return {'error': 'Credential data is required'}, 400

    try:
        # Find the credential
        credential_id = base64url_to_bytes(credential_data['id'])
        passkey = PasskeyCredential.query.filter_by(credential_id=credential_id).first()

        if not passkey:
            return {'error': 'Passkey not found'}, 401

        user = passkey.user

        # Check if user is approved
        if not user.is_approved:
            return {'error': 'Your account is pending approval. Please contact an administrator.'}, 403

        # Verify the authentication response
        verification = verify_authentication_response(
            credential=credential_data,
            expected_challenge=base64url_to_bytes(expected_challenge),
            expected_rp_id=get_rp_id(),
            expected_origin=get_origin(),
            credential_public_key=passkey.public_key,
            credential_current_sign_count=passkey.sign_count,
        )

        # Update sign count and last used
        passkey.sign_count = verification.new_sign_count
        passkey.last_used_at = datetime.utcnow()
        db.session.commit()

        # Clear session
        session.pop('passkey_auth_challenge', None)
        session.pop('passkey_auth_user_id', None)

        # Login user (passkey auth bypasses TOTP - it's already 2FA)
        login_user(user, remember=True)
        return {'user': user.to_dict()}, 200

    except Exception as e:
        current_app.logger.error(f'Passkey authentication failed: {e}')
        return {'error': f'Authentication failed: {str(e)}'}, 401


# ==================== Passkey Management ====================

@auth_bp.route('/passkeys', methods=['GET'])
@login_required
def list_passkeys():
    """List all passkeys for current user"""
    passkeys = [p.to_dict() for p in current_user.passkeys]
    return {'passkeys': passkeys}, 200


@auth_bp.route('/passkeys/<int:passkey_id>', methods=['DELETE'])
@login_required
def delete_passkey(passkey_id):
    """Delete a passkey"""
    passkey = PasskeyCredential.query.filter_by(
        id=passkey_id,
        user_id=current_user.id
    ).first()

    if not passkey:
        return {'error': 'Passkey not found'}, 404

    try:
        db.session.delete(passkey)
        db.session.commit()
        return {'message': 'Passkey deleted successfully'}, 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to delete passkey: {e}')
        return {'error': 'Failed to delete passkey'}, 500


@auth_bp.route('/passkeys/<int:passkey_id>', methods=['PUT'])
@login_required
def rename_passkey(passkey_id):
    """Rename a passkey"""
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    name = data.get('name', '').strip()
    if not name:
        return {'error': 'Name is required'}, 400

    passkey = PasskeyCredential.query.filter_by(
        id=passkey_id,
        user_id=current_user.id
    ).first()

    if not passkey:
        return {'error': 'Passkey not found'}, 404

    try:
        passkey.name = name
        db.session.commit()
        return {'message': 'Passkey renamed successfully', 'passkey': passkey.to_dict()}, 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to rename passkey: {e}')
        return {'error': 'Failed to rename passkey'}, 500
