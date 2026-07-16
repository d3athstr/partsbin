from datetime import datetime, date
from flask import Blueprint, request, current_app
from flask_login import login_required, current_user
from app import db
from app.models.order import Order, OrderItem, ORDER_VENDORS, ORDER_STATUSES
from app.models.component import Component
from app.services.stock_service import adjust_stock, receive_order_items
from app.routes import paginate_query

orders_bp = Blueprint('orders', __name__)
review_bp = Blueprint('review', __name__)


def _user_account():
    """The ingest Gmail account the current user owns ('don'/'deanna'), if any.

    Auto-assigns on first use when the username matches an INGEST_ACCOUNTS
    entry (case-insensitive); admins can override via the admin users API.
    """
    if current_user.gmail_account:
        return current_user.gmail_account
    from app.ingest.gmail_client import get_accounts
    uname = (current_user.username or '').strip().lower()
    if uname in get_accounts():
        current_user.gmail_account = uname
        db.session.commit()
        return uname
    return None


def _visible_orders():
    """Orders scoped to the current user: their Gmail account's orders plus
    orders they created manually. Users with no account mapping see only
    their own manual orders and legacy unowned ones."""
    acct = _user_account()
    if acct:
        return Order.query.filter(db.or_(
            Order.gmail_account == acct,
            Order.created_by_id == current_user.id,
        ))
    return Order.query.filter(db.or_(
        Order.created_by_id == current_user.id,
        db.and_(Order.gmail_account.is_(None), Order.created_by_id.is_(None)),
    ))


def _visible_order_or_404(id):
    order = _visible_orders().filter(Order.id == id).first()
    if order is None:
        from flask import abort
        abort(404)
    return order


ORDER_SORTS = {
    'order_date': Order.order_date,
    'vendor': Order.vendor,
    'vendor_order_no': Order.vendor_order_no,
    'total': Order.total,
    'status': Order.status,
    'created_at': Order.created_at,
    'updated_at': Order.updated_at,
}


def _parse_order_date(value):
    """Parse an ISO date string into a date, or None"""
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _suggest_for_item(item):
    """Attach a fuzzy-match suggestion to an order item if one is found"""
    try:
        from app.ingest.matcher import suggest_component
        suggestion = suggest_component(item.raw_title)
    except Exception as e:
        current_app.logger.warning(f'Matcher unavailable: {e}')
        suggestion = None
    if suggestion:
        item.suggested_component_id = suggestion
        item.match_status = 'suggested'


@orders_bp.route('', methods=['GET'])
@orders_bp.route('/', methods=['GET'])
@login_required
def list_orders():
    """List orders with status / vendor filters (scoped to the current user)"""
    query = _visible_orders()

    status = request.args.get('status')
    if status == 'all':
        pass
    elif status:
        query = query.filter(Order.status == status)
    else:
        # Default view is the active pipeline: received and ignored orders are
        # done - they only show when asked for explicitly (or with status=all).
        query = query.filter(Order.status.notin_(('received', 'ignored')))

    vendor = request.args.get('vendor')
    if vendor:
        query = query.filter(Order.vendor == vendor)

    q = (request.args.get('q') or '').strip()
    if q:
        like = f'%{q}%'
        query = query.outerjoin(OrderItem).filter(db.or_(
            Order.vendor_order_no.ilike(like),
            Order.raw_subject.ilike(like),
            OrderItem.raw_title.ilike(like),
        )).distinct()

    return paginate_query(
        query, lambda o: o.to_dict(),
        sort_map=ORDER_SORTS, default_sort='created_at',
    ), 200


@orders_bp.route('/<int:id>', methods=['GET'])
@login_required
def get_order(id):
    """Get an order with its items and matched component summaries"""
    order = _visible_order_or_404(id)
    return order.to_dict(include_items=True), 200


@orders_bp.route('', methods=['POST'])
@orders_bp.route('/', methods=['POST'])
@login_required
def create_order():
    """Manually create an order (same shape as parsed orders)"""
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    vendor = (data.get('vendor') or '').strip().lower()
    if vendor not in ORDER_VENDORS:
        return {'error': f'vendor must be one of {", ".join(ORDER_VENDORS)}'}, 400

    status = data.get('status', 'ordered')
    if status not in ORDER_STATUSES or status == 'received':
        return {'error': 'status must be ordered, shipped or delivered'}, 400

    order = Order(
        vendor=vendor,
        vendor_order_no=(data.get('vendor_order_no') or '').strip() or None,
        status=status,
        order_date=_parse_order_date(data.get('order_date')) or date.today(),
        tracking_no=(data.get('tracking_no') or '').strip() or None,
        carrier=(data.get('carrier') or '').strip() or None,
        tracking_url=(data.get('tracking_url') or '').strip() or None,
        raw_subject=(data.get('raw_subject') or '').strip() or None,
        gmail_account=_user_account(),
        created_by_id=current_user.id,
        total=data.get('total'),
        notes=data.get('notes'),
    )

    try:
        db.session.add(order)
        db.session.flush()

        for item_data in data.get('items') or []:
            raw_title = (item_data.get('raw_title') or item_data.get('title') or '').strip()
            if not raw_title:
                continue
            qty = item_data.get('qty', 1)
            if not isinstance(qty, int) or qty < 1:
                qty = 1
            item = OrderItem(
                order_id=order.id,
                raw_title=raw_title,
                qty=qty,
                unit_price=item_data.get('unit_price'),
            )
            component_id = item_data.get('component_id')
            if component_id and Component.query.get(component_id):
                item.component_id = component_id
                item.match_status = 'confirmed'
            else:
                _suggest_for_item(item)
            db.session.add(item)

        db.session.commit()
        return order.to_dict(include_items=True), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to create order: {e}')
        return {'error': 'Failed to create order'}, 500


@orders_bp.route('/<int:id>', methods=['PUT'])
@login_required
def update_order(id):
    """Manual edits to an order (status / tracking / notes)"""
    order = _visible_order_or_404(id)
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    if 'status' in data:
        status = data['status']
        if status not in ORDER_STATUSES:
            return {'error': f'status must be one of {", ".join(ORDER_STATUSES)}'}, 400
        if status == 'received' and order.status != 'received':
            return {'error': 'Use POST /receive to receive an order (it updates stock)'}, 400
        order.status = status

    for field in ('tracking_no', 'carrier', 'tracking_url', 'vendor_order_no'):
        if field in data:
            setattr(order, field, (data.get(field) or '').strip() or None)

    if 'notes' in data:
        order.notes = data['notes']

    if 'total' in data:
        order.total = data['total']

    if 'order_date' in data:
        order.order_date = _parse_order_date(data['order_date'])

    try:
        db.session.commit()
        return order.to_dict(include_items=True), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to update order: {e}')
        return {'error': 'Failed to update order'}, 500


@orders_bp.route('/<int:id>/items/<int:item_id>', methods=['PUT'])
@login_required
def update_order_item(id, item_id):
    """Match-queue decisions for an item: set component or match_status.

    Works on received orders too: un-matching reverses the stock the item
    landed, and (re-)confirming lands stock on the newly chosen component,
    so qty_on_hand always mirrors the match decisions.
    """
    item = OrderItem.query.filter_by(id=item_id, order_id=id).first_or_404()
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    from app.services.stock_service import (
        InsufficientStockError, receive_single_item, reverse_item_stock,
    )
    order_received = item.order.status == 'received'

    try:
        if 'component_id' in data:
            component = Component.query.get(data.get('component_id') or 0)
            if not component:
                return {'error': 'component_id must reference an existing component'}, 400
            if order_received and item.component_id != component.id:
                reverse_item_stock(item, user_id=current_user.id)
            item.component_id = component.id
            item.match_status = 'confirmed'
            if order_received:
                receive_single_item(item, user_id=current_user.id)
        elif 'match_status' in data:
            match_status = data['match_status']
            if match_status == 'confirmed':
                component_id = item.component_id or item.suggested_component_id
                if not component_id:
                    return {'error': 'Cannot confirm an item with no matched component'}, 400
                item.component_id = component_id
                item.match_status = 'confirmed'
                if order_received:
                    receive_single_item(item, user_id=current_user.id)
            elif match_status in ('ignored', 'unmatched'):
                if order_received:
                    reverse_item_stock(item, user_id=current_user.id)
                item.match_status = match_status
                if match_status == 'unmatched':
                    item.component_id = None
                    # "matches nothing existing": drop the suggestion too
                    if data.get('clear_suggestion'):
                        item.suggested_component_id = None
            else:
                return {'error': 'match_status must be confirmed, ignored or unmatched'}, 400
        else:
            return {'error': 'Provide component_id or match_status'}, 400
    except InsufficientStockError as e:
        db.session.rollback()
        return {'error': f'Cannot undo this match: {e}. '
                         'Adjust the component stock first.'}, 409

    try:
        db.session.commit()
        return item.to_dict(), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to update order item: {e}')
        return {'error': 'Failed to update order item'}, 500


@orders_bp.route('/<int:id>/items/<int:item_id>/create-component', methods=['POST'])
@login_required
def create_component_from_item(id, item_id):
    """Create a new component pre-filled from an order item, auto-confirms"""
    item = OrderItem.query.filter_by(id=item_id, order_id=id).first_or_404()
    data = request.get_json() or {}

    from app.routes.components import _validate_category, _set_fields

    name = (data.get('name') or item.raw_title or '').strip()[:200]
    category = (data.get('category') or 'Other').strip()

    if not name:
        return {'error': 'name is required'}, 400
    if not _validate_category(category):
        return {'error': 'category must be one of the seeded categories'}, 400

    component = Component(name=name, category=category, user_id=current_user.id)

    try:
        _set_fields(component, data)
    except ValueError as e:
        return {'error': str(e)}, 400

    try:
        db.session.add(component)
        db.session.flush()

        item.component_id = component.id
        item.match_status = 'confirmed'

        # A late match on an already-received order still owes its stock
        if item.order.status == 'received':
            from app.services.stock_service import receive_single_item
            receive_single_item(item, user_id=current_user.id)

        db.session.commit()
        return {'component': component.to_dict(), 'item': item.to_dict()}, 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to create component from item: {e}')
        return {'error': 'Failed to create component'}, 500


@orders_bp.route('/<int:id>/auto-create-components', methods=['POST'])
@login_required
def auto_create_components(id):
    """Claude-infer and create components for all pending items on an order.

    For each unmatched/suggested item: link the existing suggestion when there
    is one; otherwise ask Claude for a component definition, create it with
    qty 0 and link it. Stock still only moves on /receive.
    """
    order = _visible_order_or_404(id)
    pending = [it for it in order.items
               if it.match_status in ('unmatched', 'suggested')]
    if not pending:
        return {'message': 'No pending items on this order',
                'created': [], 'linked': [], 'failed': []}, 200

    from app.ingest.claude_parser import infer_components
    from app.ingest.matcher import suggest_component
    from app.models.category import Category

    categories = [c.name for c in Category.query.order_by(Category.id).all()]
    valid_categories = set(categories)

    try:
        inferred = infer_components([it.raw_title or '' for it in pending], categories)
    except Exception as e:
        current_app.logger.error(f'Component inference failed: {e}')
        return {'error': f'Claude inference failed: {e}'}, 502

    created, linked, failed, exploded = [], [], [], []
    known_components = Component.query.all()

    # Assortment kits explode into per-part child items instead of landing in
    # stock as one lump. Web-research their real contents up front (parallel -
    # each is a Claude call with web search, ~30-60s).
    kit_pairs = [(item, comp_def) for item, comp_def in zip(pending, inferred)
                 if item.is_kit or (comp_def and comp_def.get('is_kit'))]
    breakdowns = {}
    if kit_pairs:
        from concurrent.futures import ThreadPoolExecutor
        from app.ingest.kit_breakout import research_kit_contents
        with ThreadPoolExecutor(max_workers=min(4, len(kit_pairs))) as pool:
            futures = {
                item.id: pool.submit(research_kit_contents, item.raw_title or '',
                                     categories, order.vendor)
                for item, _ in kit_pairs
            }
            for item_id, future in futures.items():
                try:
                    breakdowns[item_id] = future.result()
                except Exception as e:
                    current_app.logger.error(f'kit research failed for item {item_id}: {e}')
                    breakdowns[item_id] = None

    def _component_for(defn, name_key='name'):
        """Match a definition against inventory or create it (qty 0)."""
        match_id = suggest_component(defn[name_key], components=known_components)
        if match_id:
            return match_id, False
        category = defn.get('category') or 'Other'
        if category not in valid_categories:
            category = 'Other'
        specs = defn.get('specs')
        component = Component(
            name=defn[name_key].strip()[:200],
            category=category,
            manufacturer=(defn.get('manufacturer') or None),
            mpn=(defn.get('mpn') or None),
            description=(defn.get('description') or None),
            specs=specs if isinstance(specs, dict) else {},
            user_id=current_user.id,
        )
        db.session.add(component)
        db.session.flush()
        known_components.append(component)
        return component.id, True

    try:
        for item, comp_def in zip(pending, inferred):
            breakdown = breakdowns.get(item.id)
            if breakdown and breakdown['found']:
                # Explode the kit: one child OrderItem per part, each matched
                # or created like a normal item. The kit item itself goes to
                # 'ignored' so receive lands stock only on the parts.
                kits = item.qty or 1
                total = breakdown.get('total_pieces')
                if item.qty_is_units and total and kits >= total and kits % total == 0:
                    # Legacy rows where the pack size was folded into qty
                    kits //= total
                for part in breakdown['parts']:
                    component_id, was_created = _component_for(part)
                    child = OrderItem(
                        order_id=order.id,
                        raw_title=part['name'],
                        qty=kits * part['qty_per_kit'],
                        qty_is_units=True,
                        match_status='confirmed',
                        component_id=component_id,
                        parent_item_id=item.id,
                    )
                    db.session.add(child)
                    if was_created:
                        created.append({'item_id': item.id, 'component_id': component_id,
                                        'name': part['name'], 'category': part['category']})
                    else:
                        linked.append({'item_id': item.id, 'component_id': component_id,
                                       'via': 'kit part'})
                item.match_status = 'ignored'
                item.component_id = None
                item.is_kit = True
                exploded.append({'item_id': item.id, 'title': item.raw_title,
                                 'parts': len(breakdown['parts']), 'kits': kits,
                                 'confidence': breakdown['confidence'],
                                 'source_url': breakdown['source_url']})
                continue
            if item.is_kit or (comp_def and comp_def.get('is_kit')):
                # Research came back empty/unverified: stock the kit whole
                # (pre-breakout behavior) rather than invent a breakdown.
                current_app.logger.warning(
                    f'kit breakout unverified for item {item.id} '
                    f'({(item.raw_title or "")[:60]!r}); keeping kit whole')

            # An ingest-time fuzzy suggestion wins - link it instead of creating a twin
            if item.suggested_component_id:
                item.component_id = item.suggested_component_id
                item.match_status = 'confirmed'
                linked.append({'item_id': item.id, 'component_id': item.component_id,
                               'via': 'suggestion'})
                continue

            if comp_def is None:
                failed.append({'item_id': item.id, 'title': item.raw_title})
                continue

            # Dedupe against inventory + components created earlier in this run
            match_id = suggest_component(comp_def['name'], components=known_components)
            if match_id:
                item.component_id = match_id
                item.match_status = 'confirmed'
                linked.append({'item_id': item.id, 'component_id': match_id,
                               'via': 'fuzzy'})
            else:
                category = comp_def.get('category') or 'Other'
                if category not in valid_categories:
                    category = 'Other'
                specs = comp_def.get('specs')
                component = Component(
                    name=comp_def['name'].strip()[:200],
                    category=category,
                    manufacturer=(comp_def.get('manufacturer') or None),
                    mpn=(comp_def.get('mpn') or None),
                    description=(comp_def.get('description') or None),
                    specs=specs if isinstance(specs, dict) else {},
                    user_id=current_user.id,
                )
                db.session.add(component)
                db.session.flush()
                known_components.append(component)
                item.component_id = component.id
                item.match_status = 'confirmed'
                created.append({'item_id': item.id, 'component_id': component.id,
                                'name': component.name, 'category': component.category})

            # Multi-packs: "100pcs ..." qty 1 should land 100 units at receive
            # (skip when the parse already folded pack size into qty)
            units = comp_def.get('units_per_item', 1) if comp_def else 1
            if units > 1 and not item.qty_is_units:
                item.qty = (item.qty or 1) * units
            item.qty_is_units = True

        # Importing an order means putting its parts in inventory: when every
        # item resolved, receive the order right here (same audited path as
        # POST /receive) so qty_on_hand updates without a second click.
        received = False
        skipped_duplicates = 0
        if not failed and order.status != 'received':
            unresolved = [it for it in order.items
                          if it.match_status not in ('confirmed', 'ignored')]
            if not unresolved:
                _, skipped_duplicates = receive_order_items(
                    order, user_id=current_user.id,
                )
                order.status = 'received'
                order.received_at = datetime.utcnow()
                received = True

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Auto-create components failed: {e}')
        return {'error': 'Failed to create components'}, 500

    # Web enrichment (image + datasheet) for the new components, off-request
    if created:
        from threading import Thread
        app_obj = current_app._get_current_object()
        new_ids = [c['component_id'] for c in created]

        def _enrich_bg():
            with app_obj.app_context():
                from app.ingest.enrich import enrich_component
                for cid in new_ids:
                    try:
                        enrich_component(cid)
                    except Exception as e:
                        app_obj.logger.warning(f'enrich component {cid}: {e}')

        Thread(target=_enrich_bg, daemon=True).start()

    return {'created': created, 'linked': linked, 'failed': failed,
            'exploded': exploded,
            'received': received, 'skipped_duplicates': skipped_duplicates,
            'order': order.to_dict(include_items=True)}, 200


@orders_bp.route('/<int:id>/receive', methods=['POST'])
@login_required
def receive_order(id):
    """Mark an order received; confirmed items increment stock"""
    order = _visible_order_or_404(id)

    if order.status == 'received':
        return {'error': 'Order has already been received'}, 400

    try:
        received_items, skipped_duplicates = receive_order_items(
            order, user_id=current_user.id,
        )

        order.status = 'received'
        order.received_at = datetime.utcnow()
        db.session.commit()

        data = order.to_dict(include_items=True)
        data['received_items'] = received_items
        data['skipped_duplicates'] = skipped_duplicates
        return data, 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to receive order: {e}')
        return {'error': 'Failed to receive order'}, 500


# ==================== Review queue ====================

def pending_review_orders():
    """Orders needing attention: unmatched/suggested items, or delivered but not received"""
    orders = (_visible_orders().filter(Order.status.notin_(('received', 'ignored')))
              .order_by(Order.created_at.desc()).all())
    pending = []
    for order in orders:
        needs_match = order.pending_item_count > 0
        needs_receive = order.status == 'delivered'
        if needs_match or needs_receive:
            data = order.to_dict(include_items=True)
            data['needs_match'] = needs_match
            data['needs_receive'] = needs_receive
            pending.append(data)
    return pending


@review_bp.route('/pending', methods=['GET'])
@login_required
def review_pending():
    """Count + orders (with items) needing a match decision or receipt"""
    orders = pending_review_orders()
    return {'count': len(orders), 'orders': orders}, 200
