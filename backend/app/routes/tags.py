from flask import Blueprint, request, current_app
from flask_login import login_required, current_user
from app import db
from app.models.tag import Tag

tags_bp = Blueprint('tags', __name__)


@tags_bp.route('', methods=['GET'])
@tags_bp.route('/', methods=['GET'])
@login_required
def get_tags():
    """Get all tags (shared across users)"""
    tags = Tag.query.order_by(Tag.name).all()
    return {'tags': [tag.to_dict() for tag in tags]}, 200


@tags_bp.route('', methods=['POST'])
@tags_bp.route('/', methods=['POST'])
@login_required
def create_tag():
    """Create a new tag"""
    data = request.get_json()

    if not data:
        return {'error': 'No data provided'}, 400

    name = data.get('name', '').strip()
    color = data.get('color', '#8ab4f8').strip()

    if not name:
        return {'error': 'Tag name is required'}, 400

    if len(name) > 50:
        return {'error': 'Tag name must be 50 characters or less'}, 400

    # Validate color format (hex color)
    if not color.startswith('#') or len(color) != 7:
        return {'error': 'Invalid color format. Use hex format (e.g., #8ab4f8)'}, 400

    # Check for duplicate tag name
    existing = Tag.query.filter(db.func.lower(Tag.name) == name.lower()).first()
    if existing:
        return {'error': 'A tag with this name already exists'}, 400

    try:
        tag = Tag(name=name, color=color, user_id=current_user.id)
        db.session.add(tag)
        db.session.commit()

        return {'tag': tag.to_dict()}, 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Failed to create tag: {e}')
        return {'error': 'Failed to create tag'}, 500
