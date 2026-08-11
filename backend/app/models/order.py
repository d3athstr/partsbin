from datetime import datetime
from app import db
from .component import JSONType

ORDER_VENDORS = ('amazon', 'aliexpress', 'adafruit', 'mouser', 'digikey', 'seeed',
                 'rokland', 'jlcpcb', 'pololu', 'other')
# 'ignored' ranks last so a later shipped/delivered email never resurrects
# an order the user discarded (ingest only upgrades status by rank).
ORDER_STATUSES = ('ordered', 'shipped', 'delivered', 'received', 'ignored')
STATUS_RANK = {status: rank for rank, status in enumerate(ORDER_STATUSES)}
MATCH_STATUSES = ('unmatched', 'suggested', 'confirmed', 'ignored')


class Order(db.Model):
    """A vendor order, usually created by the email ingestion pipeline"""
    __tablename__ = 'order'

    id = db.Column(db.Integer, primary_key=True)
    vendor = db.Column(db.String(30), nullable=False, index=True)  # one of ORDER_VENDORS
    vendor_order_no = db.Column(db.String(100), nullable=True, index=True)
    status = db.Column(db.String(20), nullable=False, default='ordered')  # one of ORDER_STATUSES
    order_date = db.Column(db.Date, nullable=True)

    # Shipping
    tracking_no = db.Column(db.String(100), nullable=True)
    carrier = db.Column(db.String(50), nullable=True)
    tracking_url = db.Column(db.String(500), nullable=True)

    # Ingestion provenance
    gmail_account = db.Column(db.String(100), nullable=True, index=True)
    # Set on manual order entry; scopes the order to its creator when there is
    # no gmail_account (visibility follows gmail_account first, then creator).
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    gmail_message_ids = db.Column(JSONType, nullable=True)  # list of gmail message ids
    raw_subject = db.Column(db.String(300), nullable=True)

    total = db.Column(db.Numeric(10, 2), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    received_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    items = db.relationship('OrderItem', backref='order', lazy='dynamic',
                            cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Order {self.vendor} {self.vendor_order_no}>'

    @property
    def pending_item_count(self):
        """Items still needing a match decision"""
        return self.items.filter(OrderItem.match_status.in_(('unmatched', 'suggested'))).count()

    def to_dict(self, include_items=False):
        """Convert order to dictionary"""
        data = {
            'id': self.id,
            'vendor': self.vendor,
            'vendor_order_no': self.vendor_order_no,
            'status': self.status,
            'order_date': self.order_date.isoformat() if self.order_date else None,
            'tracking_no': self.tracking_no,
            'carrier': self.carrier,
            'tracking_url': self.tracking_url,
            'gmail_account': self.gmail_account,
            'gmail_message_ids': self.gmail_message_ids or [],
            'raw_subject': self.raw_subject,
            'total': float(self.total) if self.total is not None else None,
            'notes': self.notes,
            'item_count': self.items.count(),
            'pending_item_count': self.pending_item_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'received_at': self.received_at.isoformat() if self.received_at else None,
        }
        if include_items:
            data['items'] = [item.to_dict() for item in self.items]
        return data


class OrderItem(db.Model):
    """Line item on an order, matched to inventory in the review queue"""
    __tablename__ = 'order_item'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False, index=True)
    raw_title = db.Column(db.Text, nullable=False)  # as parsed from the email
    qty = db.Column(db.Integer, nullable=False, default=1)
    # Price of ONE ordered line-item as the vendor billed it. A line-item can
    # be a pack ("XIAO ESP32C6 3PCS Pack" = $22.99 for three), so this is NOT
    # the price of one physical piece - divide by units_per_item for that.
    unit_price = db.Column(db.Numeric(10, 2), nullable=True)
    # Physical pieces in one ordered line-item (pack size). qty is multiplied
    # by this at auto-create, so without it the per-piece price is
    # unrecoverable once qty_is_units is set.
    units_per_item = db.Column(db.Integer, nullable=False, default=1, server_default='1')

    match_status = db.Column(db.String(20), nullable=False, default='unmatched')  # one of MATCH_STATUSES
    # True when qty already counts physical units (pack size folded in at parse
    # time); guards against multiplying again in auto-create.
    qty_is_units = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    # Assortment kit of varying values/sizes (resistor kit, standoff kit...):
    # never auto-confirmed at ingest; auto-create explodes it into per-part
    # child items instead of stocking it as one lump.
    is_kit = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    # Set on items created by exploding a kit -> the kit OrderItem they came from
    parent_item_id = db.Column(db.Integer, db.ForeignKey('order_item.id'), nullable=True)
    suggested_component_id = db.Column(db.Integer, db.ForeignKey('component.id'), nullable=True)
    component_id = db.Column(db.Integer, db.ForeignKey('component.id'), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    suggested_component = db.relationship('Component', foreign_keys=[suggested_component_id])
    component = db.relationship('Component', foreign_keys=[component_id])

    def __repr__(self):
        return f'<OrderItem {self.raw_title[:40]!r}>'

    @property
    def piece_price(self):
        """What ONE physical piece cost, unpacking multipack line pricing"""
        if self.unit_price is None:
            return None
        pack = max(int(self.units_per_item or 1), 1)
        return self.unit_price / pack

    def to_dict(self):
        """Convert order item to dictionary"""
        return {
            'id': self.id,
            'order_id': self.order_id,
            'raw_title': self.raw_title,
            'qty': self.qty,
            'unit_price': float(self.unit_price) if self.unit_price is not None else None,
            'units_per_item': self.units_per_item or 1,
            'piece_price': float(self.piece_price) if self.piece_price is not None else None,
            'match_status': self.match_status,
            'is_kit': self.is_kit,
            'parent_item_id': self.parent_item_id,
            'suggested_component_id': self.suggested_component_id,
            'suggested_component': self.suggested_component.to_summary() if self.suggested_component else None,
            'component_id': self.component_id,
            'component': self.component.to_summary() if self.component else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
