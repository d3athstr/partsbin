"""Stock movement service.

Component.qty_on_hand must ONLY change through adjust_stock() so every
movement leaves an auditable StockTransaction, and the transaction row and
quantity update always land in the same database transaction.
"""
from app import db
from app.models.component import StockTransaction, STOCK_REASONS


class InsufficientStockError(ValueError):
    """Raised when a stock movement would take qty_on_hand below zero"""


def adjust_stock(component, delta, reason, user_id=None, order_item_id=None,
                 project_component_id=None, note=None):
    """Apply a stock movement to a component.

    Creates a StockTransaction and updates component.qty_on_hand in the same
    session (flushed, not committed - the caller owns the commit so the
    movement is atomic with whatever triggered it).

    Args:
        component: Component instance
        delta: signed quantity change (non-zero int)
        reason: one of STOCK_REASONS
        user_id: acting user id (optional)
        order_item_id: OrderItem reference for order_received movements
        project_component_id: BOM line reference for project_use movements
        note: free-form note

    Returns:
        StockTransaction: the created transaction

    Raises:
        ValueError: invalid delta or reason
        InsufficientStockError: movement would make qty_on_hand negative
    """
    if not isinstance(delta, int) or delta == 0:
        raise ValueError('delta must be a non-zero integer')

    if reason not in STOCK_REASONS:
        raise ValueError(f'reason must be one of {", ".join(STOCK_REASONS)}')

    new_qty = (component.qty_on_hand or 0) + delta
    if new_qty < 0:
        raise InsufficientStockError(
            f'Insufficient stock for {component.name}: '
            f'{component.qty_on_hand} on hand, change of {delta} requested'
        )

    transaction = StockTransaction(
        component_id=component.id,
        delta=delta,
        reason=reason,
        user_id=user_id,
        order_item_id=order_item_id,
        project_component_id=project_component_id,
        note=note,
    )
    component.qty_on_hand = new_qty

    db.session.add(transaction)
    db.session.flush()
    return transaction


def _already_received_elsewhere(item):
    """True when this component already got stock from the same vendor order.

    The same physical order can appear as multiple Order rows (it emails both
    Don's and DeAnna's Gmail, or a re-parse) - stock must land only once per
    (vendor, order number, component).
    """
    from app.models.order import Order, OrderItem

    order = item.order
    if not order.vendor_order_no or not item.component_id:
        return False
    return db.session.query(StockTransaction.id).join(
        OrderItem, StockTransaction.order_item_id == OrderItem.id,
    ).join(
        Order, OrderItem.order_id == Order.id,
    ).filter(
        StockTransaction.reason == 'order_received',
        Order.vendor == order.vendor,
        Order.vendor_order_no == order.vendor_order_no,
        OrderItem.component_id == item.component_id,
        OrderItem.id != item.id,
    ).first() is not None


def receive_order_items(order, user_id=None, note=None):
    """Add stock for every confirmed item on an order (idempotent per item).

    Skips items whose component already received stock from the same vendor
    order number. Does NOT set order.status / received_at - the caller owns
    that plus the commit.

    Returns (received_count, skipped_duplicates).
    """
    received = skipped = 0
    note = note or f'{order.vendor} order {order.vendor_order_no or order.id}'
    for item in order.items:
        if item.match_status != 'confirmed' or not item.component_id:
            continue
        if _already_received_elsewhere(item):
            skipped += 1
            continue
        adjust_stock(
            item.component, item.qty, 'order_received',
            user_id=user_id,
            order_item_id=item.id,
            note=note,
        )
        received += 1
    return received, skipped


def reverse_item_stock(item, user_id=None):
    """Take back stock previously landed for an order item.

    Sums the item's transactions per component and issues compensating
    'adjustment' movements - undoing a wrong match removes exactly what
    receiving added. Net-zero items are a no-op, so this is idempotent.

    Returns the number of components adjusted.

    Raises:
        InsufficientStockError: the stock was already consumed elsewhere
    """
    from app.models.component import Component

    net = {}
    for txn in StockTransaction.query.filter_by(order_item_id=item.id):
        net[txn.component_id] = net.get(txn.component_id, 0) + txn.delta

    adjusted = 0
    for component_id, delta in net.items():
        if not delta:
            continue
        component = Component.query.get(component_id)
        if component is None:
            continue
        adjust_stock(
            component, -delta, 'adjustment',
            user_id=user_id,
            order_item_id=item.id,
            note=f'match undone: {(item.raw_title or "")[:80]}',
        )
        adjusted += 1
    return adjusted


def receive_single_item(item, user_id=None):
    """Land stock for one confirmed item on an already-received order.

    Used when a match decision is made (or corrected) after the order was
    received. Skips when the item already holds net stock on the component,
    or the same vendor order landed it via another Order row.

    Returns True when stock moved.
    """
    if item.match_status != 'confirmed' or not item.component_id:
        return False
    if _already_received_elsewhere(item):
        return False
    net = db.session.query(
        db.func.coalesce(db.func.sum(StockTransaction.delta), 0)
    ).filter(
        StockTransaction.order_item_id == item.id,
        StockTransaction.component_id == item.component_id,
    ).scalar()
    if net > 0:
        return False
    # item.component can be stale right after component_id was reassigned -
    # resolve by id so a re-match lands stock on the NEW component
    from app.models.component import Component
    component = Component.query.get(item.component_id)
    order = item.order
    adjust_stock(
        component, item.qty, 'order_received',
        user_id=user_id,
        order_item_id=item.id,
        note=f'{order.vendor} order {order.vendor_order_no or order.id} (late match)',
    )
    return True
