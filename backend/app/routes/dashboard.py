from flask import Blueprint, current_app
from flask_login import login_required
from sqlalchemy import func, or_, false as sa_false
from app import db
from app.models.component import Component
from app.models.project import Project, ProjectComponent
from app.models.order import Order
from app.routes.orders import pending_review_orders, _visible_orders

dashboard_bp = Blueprint('dashboard', __name__)


def _active_project_demand():
    """Remaining part demand from ACTIVE projects only, as {component_id: qty}.

    A project's BOM shortfalls only matter while it is being built, so
    dashboard stock warnings are driven by 'active' projects — never by
    planning / built / on_hold / retired ones. (Don, 2026-07-13.)
    """
    rows = (db.session.query(
                ProjectComponent.component_id.label('cid'),
                func.sum(ProjectComponent.qty_planned - ProjectComponent.qty_used).label('need'))
            .join(Project, Project.id == ProjectComponent.project_id)
            .filter(Project.status == 'active')
            .group_by(ProjectComponent.component_id)
            .having(func.sum(ProjectComponent.qty_planned - ProjectComponent.qty_used) > 0)
            .all())
    return {r.cid: int(r.need) for r in rows}


@dashboard_bp.route('/dashboard', methods=['GET'])
@login_required
def dashboard():
    """Exception-first dashboard: low/out-of-stock, review queue, recent orders.

    Stock warnings surface a component only when it is either (a) needed by an
    ACTIVE project that doesn't have enough on hand, or (b) below a min_qty
    'keep this stocked' threshold you set deliberately. A qty-0 catalog part
    that no active project needs (e.g. one created at qty 0 for a built/planned
    project's BOM) does NOT raise a warning.
    """
    demand = _active_project_demand()
    demand_ids = list(demand.keys())
    demand_match = Component.id.in_(demand_ids) if demand_ids else sa_false()

    # OUT OF STOCK: none on hand, and either an active project needs it or you
    # keep it stocked (min_qty > 0).
    out_of_stock = (Component.query
                    .filter(Component.qty_on_hand <= 0)
                    .filter(or_(Component.min_qty > 0, demand_match))
                    .order_by(Component.name)
                    .limit(50).all())

    # LOW STOCK: some on hand, but at/below the min_qty threshold or short of an
    # active project's remaining demand.
    low_candidates = (Component.query
                      .filter(Component.qty_on_hand > 0)
                      .filter(or_(Component.qty_on_hand <= Component.min_qty, demand_match))
                      .order_by(Component.name)
                      .limit(200).all())
    low_stock = [c for c in low_candidates
                 if (c.min_qty and c.qty_on_hand <= c.min_qty)
                 or (c.id in demand and c.qty_on_hand < demand[c.id])][:50]
    recent_orders = (_visible_orders()
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
            'orders': _visible_orders().count(),
        },
    }, 200
