from flask import Blueprint, current_app
from flask_login import login_required
from app.models.component import Component
from app.models.project import Project
from app.models.order import Order
from app.routes.orders import pending_review_orders

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/dashboard', methods=['GET'])
@login_required
def dashboard():
    """Exception-first dashboard: low/out-of-stock, review queue, recent orders"""
    low_stock = (Component.query
                 .filter(Component.qty_on_hand > 0,
                         Component.qty_on_hand <= Component.min_qty)
                 .order_by(Component.name)
                 .limit(50).all())
    out_of_stock = (Component.query
                    .filter(Component.qty_on_hand <= 0)
                    .order_by(Component.name)
                    .limit(50).all())
    recent_orders = (Order.query
                     .order_by(Order.created_at.desc())
                     .limit(5).all())

    try:
        from app.ingest.pipeline import ingest_status
        ingest = ingest_status()
    except Exception as e:
        current_app.logger.warning(f'Ingest status unavailable: {e}')
        ingest = []

    return {
        'low_stock': [c.to_dict() for c in low_stock],
        'out_of_stock': [c.to_dict() for c in out_of_stock],
        'pending_review': len(pending_review_orders()),
        'recent_orders': [o.to_dict() for o in recent_orders],
        'ingest': ingest,
        'totals': {
            'components': Component.query.count(),
            'projects': Project.query.count(),
            'orders': Order.query.count(),
        },
    }, 200
