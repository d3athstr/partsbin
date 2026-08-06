"""Component cost service.

Every component carries two prices, and they answer different questions:

  * ``est_unit_cost``  - what we EXPECT to pay. Hand-entered, or researched
    off the web by :func:`app.ingest.enrich.estimate_price`. This is what a
    project budget leans on before the part has ever been bought.
  * ``last_unit_cost`` - what we ACTUALLY paid, denormalized from the most
    recent purchase so BOM and inventory listings don't have to walk the
    order history per row.

The actual price is derived, never typed: it is the PER-PIECE price of the
newest OrderItem that is confirm-matched to the component and sits on an
order that wasn't discarded. Order items are priced per line-item, and a
line-item is often a pack ("XIAO ESP32C6 3PCS Pack" at $22.99), so the
per-piece figure is ``unit_price / units_per_item`` - see
:attr:`app.models.order.OrderItem.piece_price`. Anything that can change which item is
"newest" - receiving an order, a match decision, auto-create - must call
:func:`refresh_component_cost` (or :func:`refresh_costs_for_order`) so the
denormalized copy can't drift from the ledger it was derived from.

Costs are per unit as the vendor billed them; order quantity is never
folded in. Decimal all the way through, floats only at the JSON boundary.
"""
from datetime import datetime
from decimal import Decimal

from app import db

# An 'ignored' order is one the user discarded in the review queue - its
# prices are not evidence of anything. Every other status means money was
# committed, so the price is real even before the box arrives.
PURCHASE_ORDER_STATUSES = ('ordered', 'shipped', 'delivered', 'received')

# Money is stored at 4dp so sub-cent parts (0.0142/ea resistors) survive.
CENTS = Decimal('0.01')


def _purchase_query(component_id):
    """Order items that count as purchases of this component, newest first"""
    from app.models.order import Order, OrderItem

    return (
        OrderItem.query
        .join(Order, OrderItem.order_id == Order.id)
        .filter(
            OrderItem.component_id == component_id,
            OrderItem.match_status == 'confirmed',
            OrderItem.unit_price.isnot(None),
            Order.status.in_(PURCHASE_ORDER_STATUSES),
        )
        .order_by(Order.order_date.desc().nullslast(), Order.id.desc(),
                  OrderItem.id.desc())
    )


def latest_purchase(component_id):
    """Most recent priced purchase of a component, or None"""
    return _purchase_query(component_id).first()


def price_history(component_id, limit=20):
    """What we paid per unit over time, newest first"""
    return [
        {
            'order_id': item.order_id,
            'vendor': item.order.vendor,
            'vendor_order_no': item.order.vendor_order_no,
            'order_date': item.order.order_date.isoformat() if item.order.order_date else None,
            'qty': item.qty,
            'unit_price': float(item.piece_price),
            'pack_price': float(item.unit_price),
            'units_per_item': item.units_per_item or 1,
            'raw_title': item.raw_title,
        }
        for item in _purchase_query(component_id).limit(limit).all()
    ]


def refresh_component_cost(component):
    """Re-derive a component's actual unit cost from its purchase history.

    Writes the denormalized ``last_cost_*`` fields and flushes - the caller
    owns the commit, so the refresh stays atomic with whatever stock or
    match change triggered it.

    Returns True when anything changed.
    """
    item = latest_purchase(component.id)

    if item is None:
        # No priced purchase left (match undone, order discarded): fall back
        # to nothing rather than stranding a stale price.
        new = (None, None, None, None)
    else:
        # Store the PER-PIECE price - a BOM line multiplies it by qty_planned,
        # so a pack price here would overcharge by the pack size.
        new = (item.piece_price.quantize(Decimal('0.0001')),
               item.order.order_date, item.order.vendor, item.order_id)

    old = (component.last_unit_cost, component.last_cost_at,
           component.last_cost_vendor, component.last_cost_order_id)
    if old == new:
        return False

    (component.last_unit_cost, component.last_cost_at,
     component.last_cost_vendor, component.last_cost_order_id) = new
    db.session.flush()
    return True


def refresh_costs_for_order(order, extra_component_ids=()):
    """Refresh actual cost for every component this order touches.

    ``extra_component_ids`` covers components the order no longer points at -
    re-matching an item away from a component leaves that component holding a
    price it no longer has any evidence for.

    Returns the number of components whose cost actually moved.
    """
    from app.models.component import Component

    component_ids = {item.component_id for item in order.items if item.component_id}
    component_ids.update(cid for cid in extra_component_ids if cid)
    changed = 0
    for component_id in component_ids:
        component = Component.query.get(component_id)
        if component is not None and refresh_component_cost(component):
            changed += 1
    return changed


def refresh_all_costs():
    """Rebuild every component's actual cost from scratch (backfill / repair).

    Returns (components_scanned, components_changed). Caller commits.
    """
    from app.models.component import Component

    scanned = changed = 0
    for component in Component.query.order_by(Component.id):
        scanned += 1
        if refresh_component_cost(component):
            changed += 1
    return scanned, changed


def set_estimated_cost(component, value, source='manual'):
    """Set (or clear) a component's estimated unit cost with provenance.

    ``source`` records WHERE the number came from - 'manual' for a human,
    a URL or vendor string for a web-researched guess - so a machine
    estimate is never mistaken for a price someone actually checked.
    """
    if value is None:
        component.est_unit_cost = None
        component.est_cost_source = None
        component.est_cost_at = None
        return

    component.est_unit_cost = Decimal(value)
    component.est_cost_source = (source or 'manual')[:200]
    component.est_cost_at = datetime.utcnow()


# ==================== Project / BOM roll-up ====================

def line_costs(line):
    """Cost view of one BOM line.

    A line is priced from its own estimate override first (bulk pricing for
    one build shouldn't rewrite the catalog), then the component's estimate.
    The actual side always comes from the component's purchase history.

    ``projected`` is the number to budget with: real money where we have it,
    the estimate everywhere else.
    """
    component = line.component
    qty = max(int(line.qty_planned or 0), 0)

    override = line.est_unit_cost
    est_unit = override if override is not None else (component.est_unit_cost if component else None)
    actual_unit = component.last_unit_cost if component else None

    projected_unit = actual_unit if actual_unit is not None else est_unit
    basis = 'actual' if actual_unit is not None else ('estimated' if est_unit is not None else 'unknown')

    def extend(unit):
        return float((unit * qty).quantize(CENTS)) if unit is not None else None

    return {
        'qty_planned': qty,
        'est_unit_cost': float(est_unit) if est_unit is not None else None,
        'est_unit_cost_override': float(override) if override is not None else None,
        'component_est_unit_cost': (
            float(component.est_unit_cost)
            if component is not None and component.est_unit_cost is not None else None
        ),
        'actual_unit_cost': float(actual_unit) if actual_unit is not None else None,
        'actual_cost_at': (
            component.last_cost_at.isoformat()
            if component is not None and component.last_cost_at else None
        ),
        'actual_cost_vendor': component.last_cost_vendor if component is not None else None,
        'est_line_cost': extend(est_unit),
        'actual_line_cost': extend(actual_unit),
        'projected_line_cost': extend(projected_unit),
        'cost_basis': basis,
    }


def project_cost_summary(line_dicts):
    """Roll BOM line dicts up into a project's cost totals.

    Three totals, because they answer three different questions:

      * ``estimated_total`` - what we thought the priced-by-estimate lines
        would cost.
      * ``actual_total``    - what the already-bought lines really cost.
      * ``projected_total`` - the budget: actual where known, estimate
        elsewhere. This is the only total that spans every priced line.

    ``variance`` compares estimate to actual over ONLY the lines that have
    both, so it never reads as an overrun just because half the BOM is
    still unbought.
    """
    estimated = actual = projected = Decimal('0')
    comparable_est = comparable_actual = Decimal('0')
    with_actual = with_estimate = comparable = unpriced = 0

    for line in line_dicts:
        est = line.get('est_line_cost')
        act = line.get('actual_line_cost')
        proj = line.get('projected_line_cost')

        if est is not None:
            estimated += Decimal(str(est))
            with_estimate += 1
        if act is not None:
            actual += Decimal(str(act))
            with_actual += 1
        if proj is not None:
            projected += Decimal(str(proj))
        else:
            unpriced += 1
        if est is not None and act is not None:
            comparable_est += Decimal(str(est))
            comparable_actual += Decimal(str(act))
            comparable += 1

    variance = comparable_actual - comparable_est

    return {
        'currency': 'USD',
        'estimated_total': float(estimated.quantize(CENTS)),
        'actual_total': float(actual.quantize(CENTS)),
        'projected_total': float(projected.quantize(CENTS)),
        'line_count': len(line_dicts),
        'lines_with_estimate': with_estimate,
        'lines_with_actual': with_actual,
        'lines_unpriced': unpriced,
        # Estimate-vs-actual over the lines that have both
        'comparable_line_count': comparable,
        'comparable_estimated_total': float(comparable_est.quantize(CENTS)),
        'comparable_actual_total': float(comparable_actual.quantize(CENTS)),
        'variance': float(variance.quantize(CENTS)),
    }
