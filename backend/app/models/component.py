from datetime import datetime
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from app import db

# JSON column that uses JSONB on Postgres and plain JSON (TEXT) on sqlite
JSONType = JSON().with_variant(JSONB(), 'postgresql')

# Valid StockTransaction reasons
STOCK_REASONS = ('initial', 'order_received', 'project_use', 'adjustment')


class Component(db.Model):
    """Electronics component in inventory.

    qty_on_hand must ONLY be changed through
    app.services.stock_service.adjust_stock(), which writes a
    StockTransaction and updates the quantity atomically.
    """
    __tablename__ = 'component'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    category = db.Column(db.String(100), nullable=False, index=True)
    specs = db.Column(JSONType, nullable=True)  # free-form key/value specs
    manufacturer = db.Column(db.String(100), nullable=True)
    mpn = db.Column(db.String(100), nullable=True, index=True)  # manufacturer part number
    description = db.Column(db.Text, nullable=True)

    # Stock tracking
    qty_on_hand = db.Column(db.Integer, nullable=False, default=0)
    min_qty = db.Column(db.Integer, nullable=False, default=0)  # low-stock threshold
    location = db.Column(db.String(100), nullable=True, index=True)  # bin/drawer label

    datasheet_url = db.Column(db.String(500), nullable=True)
    image = db.Column(db.String(500), nullable=True)  # relative path under uploads/
    notes = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Foreign keys
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    # Relationships
    transactions = db.relationship(
        'StockTransaction', backref='component', lazy='dynamic',
        cascade='all, delete-orphan', order_by='StockTransaction.created_at.desc()'
    )

    def __repr__(self):
        return f'<Component {self.name}>'

    @property
    def stock_status(self):
        """ISA-101 style exception status: out / low / ok"""
        if (self.qty_on_hand or 0) <= 0:
            return 'out'
        if self.qty_on_hand <= (self.min_qty or 0):
            return 'low'
        return 'ok'

    def to_summary(self):
        """Compact representation for embedding in other payloads"""
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'mpn': self.mpn,
            'manufacturer': self.manufacturer,
            'qty_on_hand': self.qty_on_hand,
            'min_qty': self.min_qty,
            'location': self.location,
            'image': self.image,
            'image_url': f'/uploads/{self.image}' if self.image else None,
            'stock_status': self.stock_status,
        }

    def to_dict(self):
        """Convert component to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'specs': self.specs or {},
            'manufacturer': self.manufacturer,
            'mpn': self.mpn,
            'description': self.description,
            'qty_on_hand': self.qty_on_hand,
            'min_qty': self.min_qty,
            'location': self.location,
            'datasheet_url': self.datasheet_url,
            'image': self.image,
            'image_url': f'/uploads/{self.image}' if self.image else None,
            'notes': self.notes,
            'stock_status': self.stock_status,
            'tags': [t.to_dict() for t in self.tags],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class StockTransaction(db.Model):
    """Auditable stock movement record - the only path qty_on_hand changes"""
    __tablename__ = 'stock_transaction'

    id = db.Column(db.Integer, primary_key=True)
    component_id = db.Column(db.Integer, db.ForeignKey('component.id'), nullable=False, index=True)
    delta = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(30), nullable=False)  # one of STOCK_REASONS

    # Optional references to what caused the movement
    order_item_id = db.Column(db.Integer, db.ForeignKey('order_item.id'), nullable=True)
    project_component_id = db.Column(db.Integer, db.ForeignKey('project_component.id'), nullable=True)

    note = db.Column(db.String(300), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    user = db.relationship('User', foreign_keys=[user_id])

    def __repr__(self):
        return f'<StockTransaction {self.delta:+d} component {self.component_id} ({self.reason})>'

    def to_dict(self):
        """Convert transaction to dictionary"""
        return {
            'id': self.id,
            'component_id': self.component_id,
            'delta': self.delta,
            'reason': self.reason,
            'order_item_id': self.order_item_id,
            'project_component_id': self.project_component_id,
            'note': self.note,
            'user': self.user.username if self.user else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
