from flask import Blueprint, request, current_app
from flask_login import login_required, current_user
from sqlalchemy import cast, String, or_
from app import db
from app.models.component import Component
from app.models.category import Category
from app.models.tag import Tag
from app.services.file_service import FileService
from app.services.stock_service import adjust_stock, InsufficientStockError
from app.routes import paginate_query

components_bp = Blueprint('components', __name__)
catalog_bp = Blueprint('catalog', __name__)


COMPONENT_SORTS = {
    'name': Component.name,
    'category': Component.category,
    'qty_on_hand': Component.qty_on_hand,
    'location': Component.location,
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

    try:
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
