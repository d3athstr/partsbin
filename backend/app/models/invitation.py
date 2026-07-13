from datetime import datetime
import secrets
from app import db


class InvitationCode(db.Model):
    """Invitation code model for user registration"""
    __tablename__ = 'invitation_code'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False, index=True)
    # Nullable so `flask seed` can mint the bootstrap invitation before any user exists
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    used_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    used_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)  # Optional expiration
    max_uses = db.Column(db.Integer, default=1)  # Default single-use
    use_count = db.Column(db.Integer, default=0)
    note = db.Column(db.String(200), nullable=True)  # Admin note about invitation

    # Relationships
    created_by = db.relationship('User', foreign_keys=[created_by_id], backref='created_invitations')
    used_by = db.relationship('User', foreign_keys=[used_by_id], backref='used_invitation')

    def __repr__(self):
        return f'<InvitationCode {self.code}>'

    @staticmethod
    def generate_code():
        """Generate a unique invitation code"""
        return secrets.token_urlsafe(16)

    @property
    def is_valid(self):
        """Check if invitation code is still valid"""
        # Check if used up
        if self.use_count >= self.max_uses:
            return False
        # Check expiration
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        return True

    def use(self, user):
        """Mark the invitation as used by a user"""
        self.use_count += 1
        self.used_by_id = user.id
        self.used_at = datetime.utcnow()

    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'code': self.code,
            'created_by': self.created_by.username if self.created_by else None,
            'used_by': self.used_by.username if self.used_by else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'used_at': self.used_at.isoformat() if self.used_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'max_uses': self.max_uses,
            'use_count': self.use_count,
            'is_valid': self.is_valid,
            'note': self.note
        }
