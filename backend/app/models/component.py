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

    # Cost tracking. est_* is what we expect to pay (hand-entered or
    # web-researched); last_* is what we actually paid, derived from the
    # newest priced purchase by app.services.cost_service - never typed in.
    # 4dp so sub-cent parts (resistors at $0.0142/ea) survive the round trip.
    est_unit_cost = db.Column(db.Numeric(10, 4), nullable=True)
    est_cost_source = db.Column(db.String(200), nullable=True)  # 'manual' or a URL/vendor
    est_cost_at = db.Column(db.DateTime, nullable=True)

    last_unit_cost = db.Column(db.Numeric(10, 4), nullable=True)
    last_cost_at = db.Column(db.Date, nullable=True)  # order date of that purchase
    last_cost_vendor = db.Column(db.String(30), nullable=True)
    last_cost_order_id = db.Column(db.Integer, nullable=True)  # link target only, no FK

    datasheet_url = db.Column(db.String(500), nullable=True)

    # Vendor purchase reference — the canonical "buy it here" product page, the
    # vendor it points at, and that vendor's SKU (e.g. Adafruit product 258).
    # product_url is the clickable link; vendor/sku are optional metadata for a
    # tidy "Buy (Adafruit #258)" label in BOMs.
    product_url = db.Column(db.String(500), nullable=True)
    product_vendor = db.Column(db.String(30), nullable=True)  # one of ORDER_VENDORS or free text
    product_sku = db.Column(db.String(100), nullable=True)

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
        """ISA-101 style exception status: out / on_order / low / ok

        'on_order' exists so a part you have already bought stops shouting at
        you as an exception. Nothing is on the shelf, but nothing is wrong
        either -- the operator has already acted, and an alarm you cannot act
        on again is noise. It ranks BELOW 'out' and above 'low': still zero on
        hand, but no decision is owed.

        qty_on_order is a column_property defined in app/models/__init__.py.
        """
        if (self.qty_on_hand or 0) <= 0:
            return 'on_order' if (self.qty_on_order or 0) > 0 else 'out'
        if self.qty_on_hand <= (self.min_qty or 0):
            return 'low'
        return 'ok'

    @property
    def unit_cost(self):
        """Best known price per unit: what we paid, else what we expect to pay"""
        return self.last_unit_cost if self.last_unit_cost is not None else self.est_unit_cost

    @property
    def cost_basis(self):
        """Where unit_cost came from: actual / estimated / unknown"""
        if self.last_unit_cost is not None:
            return 'actual'
        if self.est_unit_cost is not None:
            return 'estimated'
        return 'unknown'

    @property
    def stock_value(self):
        """What the parts on the shelf are worth at the best known price"""
        unit = self.unit_cost
        if unit is None:
            return None
        return float(unit * max(self.qty_on_hand or 0, 0))

    def _cost_fields(self):
        """Price fields shared by to_summary() and to_dict()"""
        return {
            'est_unit_cost': float(self.est_unit_cost) if self.est_unit_cost is not None else None,
            'last_unit_cost': float(self.last_unit_cost) if self.last_unit_cost is not None else None,
            'unit_cost': float(self.unit_cost) if self.unit_cost is not None else None,
            'cost_basis': self.cost_basis,
        }

    def to_summary(self):
        """Compact representation for embedding in other payloads"""
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'mpn': self.mpn,
            'manufacturer': self.manufacturer,
            'qty_on_hand': self.qty_on_hand,
            'qty_on_order': int(self.qty_on_order or 0),
            'min_qty': self.min_qty,
            'location': self.location,
            'image': self.image,
            'image_url': f'/uploads/{self.image}' if self.image else None,
            'stock_status': self.stock_status,
            'product_url': self.product_url,
            'product_vendor': self.product_vendor,
            'product_sku': self.product_sku,
            **self._cost_fields(),
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
            'qty_on_order': int(self.qty_on_order or 0),
            'min_qty': self.min_qty,
            'location': self.location,
            'datasheet_url': self.datasheet_url,
            'product_url': self.product_url,
            'product_vendor': self.product_vendor,
            'product_sku': self.product_sku,
            'image': self.image,
            'image_url': f'/uploads/{self.image}' if self.image else None,
            'notes': self.notes,
            'stock_status': self.stock_status,
            **self._cost_fields(),
            'est_cost_source': self.est_cost_source,
            'est_cost_at': self.est_cost_at.isoformat() if self.est_cost_at else None,
            'last_cost_at': self.last_cost_at.isoformat() if self.last_cost_at else None,
            'last_cost_vendor': self.last_cost_vendor,
            'last_cost_order_id': self.last_cost_order_id,
            'stock_value': self.stock_value,
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
