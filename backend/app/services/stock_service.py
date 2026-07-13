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
