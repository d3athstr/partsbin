"""Database models"""
from app import db
from .user import User
from .passkey import PasskeyCredential
from .invitation import InvitationCode
from .tag import Tag, component_tags, project_tags
from .category import Category
from .component import Component, StockTransaction
from .project import Project, ProjectComponent, ProjectFile, ProjectAssemblyStep
from .order import Order, OrderItem
from .processed_message import ProcessedMessage

__all__ = [
    'User', 'PasskeyCredential', 'InvitationCode', 'Tag', 'component_tags',
    'project_tags', 'Category', 'Component', 'StockTransaction', 'Project',
    'ProjectComponent', 'ProjectFile', 'ProjectAssemblyStep', 'Order', 'OrderItem',
    'ProcessedMessage',
]


# ---------------------------------------------------------------------------
# Component.qty_on_order — pieces sitting on orders that have not arrived yet.
#
# Defined HERE, not in component.py, because it correlates Component against
# Order/OrderItem and doing it in the model file would be a circular import.
#
# It is a column_property (a correlated scalar subquery) rather than a Python
# property on purpose: a Python property would fire one query per component and
# turn every list view into an N+1. This way it comes back in the same SELECT
# and can also be used directly in filters, which the dashboard needs.
#
# Counts CONFIRMED matches only, on orders still in flight ('ordered' /
# 'shipped'). A 'received' order has already moved its stock into qty_on_hand,
# so counting it here would double it; 'ignored'/'discarded' never arrive.
# ---------------------------------------------------------------------------
from sqlalchemy import select, func as _func  # noqa: E402

Component.qty_on_order = db.column_property(
    select(_func.coalesce(_func.sum(OrderItem.qty), 0))
    .where(OrderItem.component_id == Component.id)
    .where(OrderItem.match_status == 'confirmed')
    .where(OrderItem.order_id == Order.id)
    .where(Order.status.in_(('ordered', 'shipped')))
    .correlate_except(OrderItem, Order)
    .scalar_subquery(),
    deferred=False,
)
