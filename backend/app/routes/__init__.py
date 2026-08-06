"""API route blueprints"""
from decimal import Decimal, InvalidOperation

from flask import request


def parse_money(value, field):
    """Parse a request money value into a non-negative Decimal, or None.

    Empty string and null both mean "clear this price" - the UI sends an
    empty input for that, and a cleared estimate must not read as $0.00.

    Raises:
        ValueError: not a number, negative, or absurdly large
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        amount = Decimal(str(value).strip().lstrip('$').replace(',', ''))
    except (InvalidOperation, ValueError):
        raise ValueError(f'{field} must be a number')
    if amount.is_nan() or amount < 0:
        raise ValueError(f'{field} must be zero or greater')
    if amount >= Decimal('1000000'):
        raise ValueError(f'{field} is unrealistically large')
    return amount.quantize(Decimal('0.0001'))


def paginate_query(query, serializer, default_per_page=25, max_per_page=200,
                   sort_map=None, default_sort=None, default_order='desc'):
    """Apply ?page=&per_page=&sort=&order= to a query and serialize the page.

    Args:
        query: SQLAlchemy query
        serializer: callable applied to each row
        default_per_page: per_page when not supplied
        max_per_page: hard cap on per_page
        sort_map: dict of sort key -> column
        default_sort: sort key used when none supplied

    Returns:
        dict: {'items': [...], 'total': n, 'page': p, 'per_page': k}
    """
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', default_per_page, type=int), max_per_page)

    sort_map = sort_map or {}
    sort = request.args.get('sort', default_sort)
    order = request.args.get('order', default_order)

    if sort and sort in sort_map:
        column = sort_map[sort]
        # nullslast both ways: sorting by a nullable column (a price, a
        # location) should surface rows that HAVE a value, not the blanks -
        # Postgres otherwise leads a descending sort with every NULL.
        direction = column.asc() if order == 'asc' else column.desc()
        query = query.order_by(direction.nullslast())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return {
        'items': [serializer(item) for item in pagination.items],
        'total': pagination.total,
        'page': page,
        'per_page': per_page,
    }
