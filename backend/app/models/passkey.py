from datetime import datetime
from app import db


class PasskeyCredential(db.Model):
    """Stores WebAuthn credentials for passkey authentication"""
    __tablename__ = 'passkey_credential'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # WebAuthn credential fields
    credential_id = db.Column(db.LargeBinary, nullable=False, unique=True)
    public_key = db.Column(db.LargeBinary, nullable=False)
    sign_count = db.Column(db.Integer, nullable=False, default=0)

    # Credential metadata
    name = db.Column(db.String(100), nullable=False, default='My Passkey')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime, nullable=True)

    # Transports (e.g., 'usb', 'nfc', 'ble', 'internal')
    transports = db.Column(db.String(200), nullable=True)

    # Relationship
    user = db.relationship('User', back_populates='passkeys')

    def __repr__(self):
        return f'<PasskeyCredential {self.name} for user {self.user_id}>'

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'name': self.name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
        }
