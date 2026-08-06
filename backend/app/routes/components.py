from flask import Blueprint, request, current_app
from flask_login import login_required, current_user
from sqlalchemy import cast, String, or_
from app import db
from app.models.component import Component
from app.models.category import Category
from app.models.tag import Tag
from app.services.file_service import FileService
from app.services.stock_service import adjust_stock, InsufficientStockError
from app.services import cost_service
from app.routes import paginate_query, parse_money

components_bp = Blueprint('components', __name__)
catalog_bp = Blueprint('catalog', __name__)


COMPONENT_SORTS = {
    'name': Component.name,
    'category': Component.category,
    'qty_on_hand': Component.qty_on_hand,
    'location': Component.location,
    'est_unit_cost': Component.est_unit_cost,
    'last_unit_cost': Component.last_unit_cost,
    'created_at': Component.created_at,
    'updated_at': Component.updated_at,
}


def _apply_tags(component, tag_values):
    """Replace a component's tags from a list of names or ids"""
    tags = []
    for value in tag_values:
        if isinstance(value, int):
            tag = Tag.query.get(value)
            if tag:
                tags.append(tag)
        elif isinstance(value, str) and value.strip():
            tags.append(Tag.get_or_create(value, user_id=current_user.id))
    component.tags = tags


def _validate_category(name):
    """Check a category name against the seeded fixed list"""
    if not name:
        return False
    return Category.query.filter_by(name=name).first() is not None


def _set_fields(component, data):
    """Apply updatable fields from a request payload"""
    for field in ('name', 'category', 'manufacturer', 'mpn', 'description',
                  'location', 'datasheet_url', 'notes'):
        if field in data:
            value = data[field]
            setattr(component, field, value.strip() if isinstance(value, str) else value)

    if 'specs' in data:
        specs = data['specs']
        if specs is not None and not isinstance(specs, dict):
            raise ValueError('specs must be an object of key/value pairs')
        component.specs = specs or {}

    if 'min_qty' in data:
        try:
            component.min_qty = max(int(data['min_qty']), 0)
        except (ValueError, TypeError):
            raise ValueError('min_qty must be an integer')

    # Only the ESTIMATE is settable - the actual cost is derived from order
    # history by cost_service and would be overwritten on the next refresh.
    if 'est_unit_cost' in data:
        cost_service.set_estimated_cost(
            component, parse_money(data['est_unit_cost'], 'est_unit_cost'),
            source='manual',
        )

    if 'tags' in data and isinstance(data['tags'], list):
        _apply_tags(component, data['tags'])


@components_bp.route('', methods=['GET'])
@components_bp.route('/', methods=['GET'])
@login_required
def list_components():
    """List components with search, filters, pagination and sorting"""
    query = Component.query

    search = request.args.get('search', '').strip()
    if search:
        like = f'%{search}%'
        query = query.filter(or_(
            Component.name.ilike(like),
            Component.mpn.ilike(like),
            Component.manufacturer.ilike(like),
            Component.description.ilike(like),
            Component.location.ilike(like),
            cast(Component.specs, String).ilike(like),
        ))

    category = request.args.get('category')
    if category:
        query = query.filter(Component.category == category)

    tag = request.args.get('tag')
    if tag:
        query = query.join(Component.tags).filter(Tag.name == tag)

    location = request.args.get('location')
    if location:
        query = query.filter(Component.location == location)

    if request.args.get('low_stock') == '1':
        query = query.filter(Component.qty_on_hand <= Component.min_qty)

    if request.args.get('out_of_stock') == '1':
        query = query.filter(Component.qty_on_hand <= 0)

    return paginate_query(
        query, lambda c: c.to_dict(),
        sort_map=COMPONENT_SORTS, default_sort='name', default_order='asc',
    ), 200


@components_bp.route('/<int:id>', methods=['GET'])
@login_required
def get_component(id):
    """Get a component with recent transactions and used-in projects"""
    component = Component.query.get_or_404(id)

    data = component.to_dict()
    data['transactions'] = [t.to_dict() for t in component.transactions.limit(20)]
    data['used_in'] = [
        {
            'project': line.project.to_summary(),
            'qty_planned': line.qty_planned,
            'qty_used': line.qty_used,
        }
        for line in component.project_links
    ]

    from app.models.order import Order, OrderItem
    order_items = (
        OrderItem.query.filter_by(component_id=component.id)
        .join(Order)
        .order_by(Order.order_date.desc().nullslast(), Order.id.desc())
        .limit(50)
        .all()
    )
    data['orders'] = [
        {
            'order_id': it.order_id,
            'vendor': it.order.vendor,
            'vendor_order_no': it.order.vendor_order_no,
            'order_date': it.order.order_date.isoformat() if it.order.order_date else None,
            'status': it.order.status,
            'qty': it.qty,
            'unit_price': float(it.unit_price) if it.unit_price is not None else None,
            'raw_title': it.raw_title,
        }
        for it in order_items
    ]

    data['cost'] = {
        'currency': 'USD',
        'est_unit_cost': data['est_unit_cost'],
        'est_cost_source': component.est_cost_source,
        'est_cost_at': data['est_cost_at'],
        'last_unit_cost': data['last_unit_cost'],
        'last_cost_at': data['last_cost_at'],
        'last_cost_vendor': component.last_cost_vendor,
        'last_cost_order_id': component.last_cost_order_id,
        'unit_cost': data['unit_cost'],
        'cost_basis': data['cost_basis'],
        'stock_value': data['stock_value'],
        'history': cost_service.price_history(component.id),
    }
    return data, 200


@components_bp.route('', methods=['POST'])
@components_bp.route('/', methods=['POST'])
@login_required
def create_component():
    """Create a new component (initial stock recorded as a transaction)"""
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    name = (data.get('name') or '').strip()
    category = (data.get('category') or '').strip()

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
        db.session.flush()  # Get component.id before the initial transaction

        initial_qty = data.get('qty_on_hand', 0)
        if not isinstance(initial_qty, int) or initial_qty < 0:
            db.session.rollback()
            return {'error': 'qty_on_hand must be a non-negative integer'}, 400
        if initial_qty > 0:
            adjust_stock(component, initial_qty, 'initial',
                         user_id=current_user.id, note='Initial stock')

        db.session.commit()
        return component.to_dict(), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to create component: {e}')
        return {'error': 'Failed to create component'}, 500


@components_bp.route('/<int:id>', methods=['PUT'])
@login_required
def update_component(id):
    """Update a component (stock changes must go through /adjust)"""
    component = Component.query.get_or_404(id)
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    if 'qty_on_hand' in data and data['qty_on_hand'] != component.qty_on_hand:
        return {'error': 'qty_on_hand cannot be edited directly - use POST /adjust'}, 400

    if 'last_unit_cost' in data:
        return {'error': 'last_unit_cost is derived from order history and cannot '
                         'be edited - set est_unit_cost instead'}, 400

    if 'category' in data and not _validate_category((data.get('category') or '').strip()):
        return {'error': 'category must be one of the seeded categories'}, 400

    if 'name' in data and not (data.get('name') or '').strip():
        return {'error': 'name cannot be empty'}, 400

    try:
        _set_fields(component, data)
        db.session.commit()
        return component.to_dict(), 200
    except ValueError as e:
        db.session.rollback()
        return {'error': str(e)}, 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to update component: {e}')
        return {'error': 'Failed to update component'}, 500


@components_bp.route('/<int:id>', methods=['DELETE'])
@login_required
def delete_component(id):
    """Delete a component, its files and its stock history"""
    component = Component.query.get_or_404(id)

    if component.project_links.count() > 0:
        return {'error': 'Component is used in a project BOM - remove it there first'}, 409

    from app.models.order import OrderItem
    from app.models.component import StockTransaction

    try:
        # Release order-item links (items return to the review queue) and drop
        # the stock ledger - it is meaningless without its component.
        for item in OrderItem.query.filter_by(component_id=component.id).all():
            item.component_id = None
            if item.match_status == 'confirmed':
                item.match_status = 'unmatched'
        for item in OrderItem.query.filter_by(suggested_component_id=component.id).all():
            item.suggested_component_id = None
            if item.match_status == 'suggested':
                item.match_status = 'unmatched'
        StockTransaction.query.filter_by(component_id=component.id).delete()

        FileService.delete_component_files(component.id)
        db.session.delete(component)
        db.session.commit()
        return {'message': 'Component deleted successfully'}, 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to delete component: {e}')
        return {'error': 'Failed to delete component'}, 500


@components_bp.route('/<int:id>/adjust', methods=['POST'])
@login_required
def adjust_component_stock(id):
    """Manual stock adjustment (creates an 'adjustment' transaction)"""
    component = Component.query.get_or_404(id)
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    delta = data.get('delta')
    if not isinstance(delta, int) or delta == 0:
        return {'error': 'delta must be a non-zero integer'}, 400

    try:
        transaction = adjust_stock(
            component, delta, 'adjustment',
            user_id=current_user.id, note=(data.get('note') or '').strip() or None,
        )
        db.session.commit()
        return {
            'component': component.to_dict(),
            'transaction': transaction.to_dict(),
        }, 200
    except InsufficientStockError as e:
        db.session.rollback()
        return {'error': str(e)}, 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to adjust stock: {e}')
        return {'error': 'Failed to adjust stock'}, 500


@components_bp.route('/<int:id>/image', methods=['POST'])
@login_required
def upload_component_image(id):
    """Upload (or replace) a component image (multipart)"""
    component = Component.query.get_or_404(id)

    file = request.files.get('image') or request.files.get('file')
    if not file:
        return {'error': 'No image file provided'}, 400

    try:
        component.image = FileService.save_component_image(component, file)
        db.session.commit()
        return component.to_dict(), 200
    except ValueError as e:
        db.session.rollback()
        return {'error': str(e)}, 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to save component image: {e}')
        return {'error': 'Failed to save image'}, 500


@components_bp.route('/from-url', methods=['POST'])
@login_required
def component_from_url_route():
    """Draft a component from a product-page URL (Claude web_fetch/search)"""
    data = request.get_json() or {}
    url = (data.get('url') or '').strip()
    if not url:
        return {'error': 'A product URL or product title is required'}, 400

    from app.ingest.enrich import component_from_url
    categories = [c.name for c in Category.query.order_by(Category.position, Category.name).all()]
    try:
        draft = component_from_url(url, categories)
    except Exception as e:
        current_app.logger.error(f'from-url failed for {url}: {e}')
        return {'error': f'Could not read that product page: {e}'}, 502
    if draft is None:
        if 'aliexpress' in url.lower():
            return {'error': 'AliExpress blocks automated readers and its URLs '
                             'carry no product info - paste the product TITLE '
                             'from the listing instead'}, 422
        return {'error': 'Could not extract a component - try pasting the '
                         'product title instead of the URL'}, 422
    if draft.get('category') not in {c for c in categories}:
        draft['category'] = 'Other'
    draft['source_url'] = url
    return {'draft': draft}, 200


@components_bp.route('/<int:id>/attach-image', methods=['POST'])
@login_required
def attach_component_image(id):
    """Download a web image (from from-url draft candidates) onto a component"""
    component = Component.query.get_or_404(id)
    data = request.get_json() or {}
    urls = data.get('urls') or ([data['url']] if data.get('url') else [])
    from app.ingest.enrich import attach_image_from_urls
    if component.image:
        return {'component': component.to_dict(), 'attached': False}, 200
    attached = attach_image_from_urls(component, urls)
    if attached:
        db.session.commit()
    return {'component': component.to_dict(), 'attached': attached}, 200


@components_bp.route('/<int:id>/lookup', methods=['POST'])
@login_required
def lookup_component(id):
    """Web-search candidate identifications with a user-provided hint"""
    component = Component.query.get_or_404(id)
    data = request.get_json() or {}
    hint = (data.get('query') or '').strip()
    from app.ingest.enrich import search_component_candidates
    try:
        candidates = search_component_candidates(component, hint)
    except Exception as e:
        current_app.logger.error(f'Lookup failed for component {id}: {e}')
        return {'error': f'Lookup failed: {e}'}, 502
    return {'candidates': candidates}, 200


@components_bp.route('/<int:id>/apply-candidate', methods=['POST'])
@login_required
def apply_component_candidate(id):
    """Apply a user-chosen lookup candidate (image/datasheet replace, rest fills)"""
    component = Component.query.get_or_404(id)
    data = request.get_json() or {}
    candidate = data.get('candidate')
    if not isinstance(candidate, dict):
        return {'error': 'candidate object required'}, 400
    from app.ingest.enrich import apply_candidate
    try:
        result = apply_candidate(component, candidate)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Apply candidate failed for component {id}: {e}')
        return {'error': 'Failed to apply candidate'}, 500
    return {'applied': result, 'component': component.to_dict()}, 200


@components_bp.route('/<int:id>/enrich', methods=['POST'])
@login_required
def enrich_component_route(id):
    """Web-search an image + datasheet for this component (skips human-set assets)"""
    component = Component.query.get_or_404(id)
    from app.ingest.enrich import enrich_component
    try:
        result = enrich_component(component.id, force=True)
    except Exception as e:
        current_app.logger.error(f'Enrich failed for component {id}: {e}')
        return {'error': f'Enrichment failed: {e}'}, 502
    return {'enriched': result, 'component': component.to_dict()}, 200


@components_bp.route('/<int:id>/estimate-price', methods=['POST'])
@login_required
def estimate_component_price(id):
    """Web-search a current street price into est_unit_cost.

    Never touches last_unit_cost (that is what we really paid) and, unless
    force=true, never overwrites an estimate a human already set.
    """
    component = Component.query.get_or_404(id)
    data = request.get_json() or {}
    force = bool(data.get('force'))

    if component.est_unit_cost is not None and not force:
        return {'error': 'This component already has an estimate - pass '
                         'force=true to replace it'}, 409

    from app.ingest.enrich import estimate_price
    try:
        result = estimate_price(component)
    except Exception as e:
        current_app.logger.error(f'Price estimate failed for component {id}: {e}')
        return {'error': f'Price lookup failed: {e}'}, 502

    if result is None:
        return {'error': 'Could not find a current price for this part - '
                         'enter one by hand'}, 422

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to save price estimate for {id}: {e}')
        return {'error': 'Failed to save the estimate'}, 500

    return {'estimate': result, 'component': component.to_dict()}, 200


@components_bp.route('/<int:id>/refresh-cost', methods=['POST'])
@login_required
def refresh_component_cost_route(id):
    """Re-derive this component's actual unit cost from its order history"""
    component = Component.query.get_or_404(id)
    try:
        changed = cost_service.refresh_component_cost(component)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to refresh cost for component {id}: {e}')
        return {'error': 'Failed to refresh cost'}, 500
    return {'changed': changed, 'component': component.to_dict()}, 200


@components_bp.route('/<int:id>/transactions', methods=['GET'])
@login_required
def list_component_transactions(id):
    """Stock transaction history for a component"""
    component = Component.query.get_or_404(id)
    query = component.transactions
    return paginate_query(query, lambda t: t.to_dict(), default_per_page=50), 200


# ==================== Catalog (categories / locations) ====================

@catalog_bp.route('/categories', methods=['GET'])
@login_required
def list_categories():
    """Fixed seeded category list"""
    categories = Category.query.order_by(Category.position, Category.name).all()
    return {'categories': [c.to_dict() for c in categories]}, 200


@catalog_bp.route('/locations', methods=['GET'])
@login_required
def list_locations():
    """Distinct location strings in use"""
    rows = (db.session.query(Component.location)
            .filter(Component.location.isnot(None), Component.location != '')
            .distinct().order_by(Component.location).all())
    return {'locations': [row[0] for row in rows]}, 200
