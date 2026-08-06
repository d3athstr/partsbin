"""Add component/BOM cost columns and backfill actual costs (2026-08-06).

PartsBin's schema is created by db.create_all(), which never ALTERs an
existing table - new columns land here instead. Idempotent: every ADD COLUMN
is IF NOT EXISTS, and the backfill re-derives from the order ledger, so
re-running it is a no-op rather than a double-count.

    cd /opt/partsbin/backend && venv/bin/python scripts/add_cost_columns_20260806.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from app import create_app, db  # noqa: E402

STATEMENTS = [
    # What we expect to pay (hand-entered or web-researched)
    "ALTER TABLE component ADD COLUMN IF NOT EXISTS est_unit_cost NUMERIC(10,4)",
    "ALTER TABLE component ADD COLUMN IF NOT EXISTS est_cost_source VARCHAR(200)",
    "ALTER TABLE component ADD COLUMN IF NOT EXISTS est_cost_at TIMESTAMP",
    # What we actually paid, derived from the newest priced purchase
    "ALTER TABLE component ADD COLUMN IF NOT EXISTS last_unit_cost NUMERIC(10,4)",
    "ALTER TABLE component ADD COLUMN IF NOT EXISTS last_cost_at DATE",
    "ALTER TABLE component ADD COLUMN IF NOT EXISTS last_cost_vendor VARCHAR(30)",
    "ALTER TABLE component ADD COLUMN IF NOT EXISTS last_cost_order_id INTEGER",
    # Per-project estimate override
    "ALTER TABLE project_component ADD COLUMN IF NOT EXISTS est_unit_cost NUMERIC(10,4)",
]


def main():
    app = create_app(os.getenv('FLASK_ENV', 'production'))
    with app.app_context():
        for statement in STATEMENTS:
            db.session.execute(text(statement))
        db.session.commit()
        print(f'{len(STATEMENTS)} column statement(s) applied')

        from app.services.cost_service import refresh_all_costs

        scanned, changed = refresh_all_costs()
        db.session.commit()
        print(f'backfill: scanned {scanned} components, priced {changed} from order history')


if __name__ == '__main__':
    main()
