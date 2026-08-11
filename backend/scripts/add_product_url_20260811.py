"""Add component vendor-purchase-reference columns (2026-08-11).

PartsBin's schema is created by db.create_all(), which never ALTERs an
existing table - new columns land here instead. Idempotent: every ADD COLUMN
is IF NOT EXISTS, so re-running is a no-op.

Adds the canonical "buy it here" reference to a component:
  product_url    - the vendor product page (clickable link in the UI + BOM)
  product_vendor - which vendor it is (one of ORDER_VENDORS, or free text)
  product_sku    - that vendor's SKU (e.g. Adafruit product 258)

    cd /opt/partsbin/backend && venv/bin/python scripts/add_product_url_20260811.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from app import create_app, db  # noqa: E402

STATEMENTS = [
    "ALTER TABLE component ADD COLUMN IF NOT EXISTS product_url VARCHAR(500)",
    "ALTER TABLE component ADD COLUMN IF NOT EXISTS product_vendor VARCHAR(30)",
    "ALTER TABLE component ADD COLUMN IF NOT EXISTS product_sku VARCHAR(100)",
]


def main():
    app = create_app(os.getenv('FLASK_ENV', 'production'))
    with app.app_context():
        for statement in STATEMENTS:
            db.session.execute(text(statement))
        db.session.commit()
        print(f'{len(STATEMENTS)} column statement(s) applied')


if __name__ == '__main__':
    main()
