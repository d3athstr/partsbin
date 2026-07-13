from flask import Blueprint, request, current_app
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime, timedelta
import re
from app import db
from app.models.user import User
from app.models.invitation import InvitationCode
from app.services.email_service import send_invitation_email

admin_bp = Blueprint('admin', __name__)


def admin_required(f):
    """Decorator to require admin access"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            return {'error': 'Admin access required'}, 403
        return f(*args, **kwargs)
    return decorated_function


@admin_bp.route('/users', methods=['GET'])
@admin_required
def list_users():
    """List all users for admin management"""
    users = User.query.order_by(User.created_at.desc()).all()
    return {
        'users': [u.to_dict() for u in users]
    }, 200


@admin_bp.route('/users/<int:user_id>/approve', methods=['PUT'])
@admin_required
def approve_user(user_id):
    """Approve a user to access the site"""
    user = User.query.get_or_404(user_id)

    # Can't modify yourself
    if user.id == current_user.id:
        return {'error': 'Cannot modify your own approval status'}, 400

    user.is_approved = True

    try:
        db.session.commit()
        return {'message': f'User {user.username} approved', 'user': user.to_dict()}, 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to approve user: {e}')
        return {'error': 'Failed to approve user'}, 500


@admin_bp.route('/users/<int:user_id>/revoke', methods=['PUT'])
@admin_required
def revoke_user(user_id):
    """Revoke a user's access to the site"""
    user = User.query.get_or_404(user_id)

    # Can't modify yourself
    if user.id == current_user.id:
        return {'error': 'Cannot revoke your own access'}, 400

    user.is_approved = False

    try:
        db.session.commit()
        return {'message': f'User {user.username} access revoked', 'user': user.to_dict()}, 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to revoke user: {e}')
        return {'error': 'Failed to revoke user'}, 500


@admin_bp.route('/users/<int:user_id>/admin', methods=['PUT'])
@admin_required
def toggle_admin(user_id):
    """Toggle admin status for a user"""
    user = User.query.get_or_404(user_id)

    # Can't modify yourself
    if user.id == current_user.id:
        return {'error': 'Cannot modify your own admin status'}, 400

    data = request.get_json() or {}
    is_admin = data.get('is_admin', not user.is_admin)

    user.is_admin = is_admin
    # Admins should also be approved
    if is_admin:
        user.is_approved = True

    try:
        db.session.commit()
        status = 'granted admin access' if user.is_admin else 'removed from admin'
        return {'message': f'User {user.username} {status}', 'user': user.to_dict()}, 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to toggle admin: {e}')
        return {'error': 'Failed to update admin status'}, 500


@admin_bp.route('/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    """Delete a user"""
    user = User.query.get_or_404(user_id)

    # Can't delete yourself
    if user.id == current_user.id:
        return {'error': 'Cannot delete your own account'}, 400

    username = user.username

    try:
        db.session.delete(user)
        db.session.commit()
        return {'message': f'User {username} deleted'}, 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to delete user: {e}')
        return {'error': 'Failed to delete user'}, 500


# ==================== Invitation Code Management ====================

@admin_bp.route('/invitations', methods=['GET'])
@admin_required
def list_invitations():
    """List all invitation codes"""
    invitations = InvitationCode.query.order_by(InvitationCode.created_at.desc()).all()
    return {
        'invitations': [inv.to_dict() for inv in invitations]
    }, 200


def is_valid_email(email):
    """Simple email validation"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


@admin_bp.route('/invitations', methods=['POST'])
@admin_required
def create_invitation():
    """Create a new invitation code, optionally send via email"""
    data = request.get_json() or {}

    # Optional parameters
    max_uses = data.get('max_uses', 1)
    note = data.get('note', '').strip()
    expires_in_days = data.get('expires_in_days')
    send_to_email = data.get('email', '').strip()

    # Validate max_uses
    if not isinstance(max_uses, int) or max_uses < 1:
        return {'error': 'max_uses must be a positive integer'}, 400

    # Validate email if provided
    if send_to_email and not is_valid_email(send_to_email):
        return {'error': 'Invalid email address'}, 400

    # Create invitation
    invitation = InvitationCode(
        code=InvitationCode.generate_code(),
        created_by_id=current_user.id,
        max_uses=max_uses,
        note=note if note else None
    )

    # Set expiration if specified
    if expires_in_days:
        try:
            days = int(expires_in_days)
            if days > 0:
                invitation.expires_at = datetime.utcnow() + timedelta(days=days)
        except (ValueError, TypeError):
            pass

    try:
        db.session.add(invitation)
        db.session.commit()

        # Send email if requested
        email_sent = False
        if send_to_email:
            email_sent = send_invitation_email(
                to_email=send_to_email,
                invitation_code=invitation.code,
                inviter_name=current_user.username,
                note=note if note else None
            )

        response = {
            'message': 'Invitation code created',
            'invitation': invitation.to_dict()
        }

        if send_to_email:
            response['email_sent'] = email_sent
            if email_sent:
                response['message'] = f'Invitation sent to {send_to_email}'
            else:
                response['message'] = 'Invitation created but email failed to send'

        return response, 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to create invitation: {e}')
        return {'error': 'Failed to create invitation code'}, 500


@admin_bp.route('/invitations/<int:invitation_id>/resend', methods=['POST'])
@admin_required
def resend_invitation(invitation_id):
    """Resend an invitation email"""
    invitation = InvitationCode.query.get_or_404(invitation_id)
    data = request.get_json() or {}

    email = data.get('email', '').strip()
    if not email:
        return {'error': 'Email address is required'}, 400

    if not is_valid_email(email):
        return {'error': 'Invalid email address'}, 400

    if not invitation.is_valid:
        return {'error': 'This invitation code is no longer valid'}, 400

    # Send the email
    email_sent = send_invitation_email(
        to_email=email,
        invitation_code=invitation.code,
        inviter_name=current_user.username,
        note=invitation.note
    )

    if email_sent:
        return {'message': f'Invitation resent to {email}'}, 200
    else:
        return {'error': 'Failed to send email'}, 500


@admin_bp.route('/invitations/<int:invitation_id>', methods=['DELETE'])
@admin_required
def delete_invitation(invitation_id):
    """Delete an invitation code"""
    invitation = InvitationCode.query.get_or_404(invitation_id)

    try:
        db.session.delete(invitation)
        db.session.commit()
        return {'message': 'Invitation code deleted'}, 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to delete invitation: {e}')
        return {'error': 'Failed to delete invitation code'}, 500


@admin_bp.route('/invitations/<int:invitation_id>', methods=['PUT'])
@admin_required
def update_invitation(invitation_id):
    """Update an invitation code (note, max_uses, expiration)"""
    invitation = InvitationCode.query.get_or_404(invitation_id)
    data = request.get_json() or {}

    # Update fields if provided
    if 'note' in data:
        invitation.note = data['note'].strip() if data['note'] else None

    if 'max_uses' in data:
        max_uses = data['max_uses']
        if isinstance(max_uses, int) and max_uses >= invitation.use_count:
            invitation.max_uses = max_uses

    if 'expires_in_days' in data:
        expires_in_days = data['expires_in_days']
        if expires_in_days is None:
            invitation.expires_at = None
        else:
            try:
                days = int(expires_in_days)
                if days > 0:
                    invitation.expires_at = datetime.utcnow() + timedelta(days=days)
            except (ValueError, TypeError):
                pass

    try:
        db.session.commit()
        return {
            'message': 'Invitation code updated',
            'invitation': invitation.to_dict()
        }, 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to update invitation: {e}')
        return {'error': 'Failed to update invitation code'}, 500
