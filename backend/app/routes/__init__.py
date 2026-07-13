"""API route blueprints"""
from flask import request


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
        query = query.order_by(column.asc() if order == 'asc' else column.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return {
        'items': [serializer(item) for item in pagination.items],
        'total': pagination.total,
        'page': page,
        'per_page': per_page,
    }
