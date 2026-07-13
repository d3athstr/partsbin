from datetime import datetime
from flask_login import UserMixin
import bcrypt
from app import db


class User(db.Model, UserMixin):
    """User model"""
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    email = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_approved = db.Column(db.Boolean, default=False)  # Must be approved by admin to access site
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # TOTP 2FA fields
    totp_secret_encrypted = db.Column(db.String(200), nullable=True)
    totp_enabled = db.Column(db.Boolean, default=False)

    # Relationships
    passkeys = db.relationship('PasskeyCredential', back_populates='user', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<User {self.username}>'

    def set_password(self, password):
        """Hash and set password using bcrypt"""
        salt = bcrypt.gensalt(rounds=12)
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    def check_password(self, password):
        """Verify password against stored hash"""
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))

    def set_totp_secret(self, secret, cipher_suite):
        """Encrypt and store TOTP secret"""
        if cipher_suite and secret:
            encrypted = cipher_suite.encrypt(secret.encode('utf-8'))
            self.totp_secret_encrypted = encrypted.decode('utf-8')

    def get_totp_secret(self, cipher_suite):
        """Decrypt and return TOTP secret"""
        if cipher_suite and self.totp_secret_encrypted:
            try:
                decrypted = cipher_suite.decrypt(self.totp_secret_encrypted.encode('utf-8'))
                return decrypted.decode('utf-8')
            except Exception:
                return None
        return None

    @property
    def has_passkeys(self):
        """Check if user has any registered passkeys"""
        return self.passkeys.count() > 0

    def to_dict(self, include_admin_fields=False):
        """Convert user to dictionary (excludes sensitive data)"""
        data = {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'totp_enabled': self.totp_enabled or False,
            'has_passkeys': self.has_passkeys,
            'passkey_count': self.passkeys.count(),
            'is_admin': self.is_admin or False,
            'is_approved': self.is_approved or False,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
        return data
