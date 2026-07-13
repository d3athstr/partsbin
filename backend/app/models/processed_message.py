from datetime import datetime
from app import db


class ProcessedMessage(db.Model):
    """Gmail message-id dedup table so ingestion polling is idempotent"""
    __tablename__ = 'processed_message'
    __table_args__ = (
        db.UniqueConstraint('gmail_account', 'message_id', name='uq_processed_message'),
    )

    id = db.Column(db.Integer, primary_key=True)
    gmail_account = db.Column(db.String(100), nullable=False, index=True)
    message_id = db.Column(db.String(100), nullable=False, index=True)
    is_order = db.Column(db.Boolean, nullable=False, default=False)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=True)
    processed_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<ProcessedMessage {self.gmail_account}/{self.message_id}>'

    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'gmail_account': self.gmail_account,
            'message_id': self.message_id,
            'is_order': self.is_order,
            'order_id': self.order_id,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
        }
