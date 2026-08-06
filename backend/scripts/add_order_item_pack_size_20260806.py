"""Add OrderItem.units_per_item and recover it for legacy rows (2026-08-06).

OrderItem.unit_price is the price of ONE ordered line-item, and a line-item
is frequently a pack ("XIAO ESP32C6 3PCS Pack" = $22.99 for three). Auto-create
multiplies qty by the pack size and sets qty_is_units, but the pack size itself
was never stored - so per-piece cost was unrecoverable. This adds the column,
populated going forward by the auto-create path.

LEGACY BACKFILL AND ITS ASSUMPTION: for already-processed rows the pack size
is inferred as units_per_item = qty, i.e. ONE pack was ordered on that line.
Every sampled row matched (a "50Pcs" listing landed qty=50, a "2-Pack" landed
qty=2), and it is the overwhelmingly common case for this inventory. Where it
is wrong - two packs bought on one line - that component's actual price reads
high by the number of packs, and the fix is to re-derive after correcting the
line, or to set an estimate by hand.

Rows with no price, and kit children (which carry no price of their own), are
left at 1.

    cd /opt/partsbin/backend && venv/bin/python scripts/add_order_item_pack_size_20260806.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from app import create_app, db  # noqa: E402

ADD_COLUMN = (
    "ALTER TABLE order_item ADD COLUMN IF NOT EXISTS "
    "units_per_item INTEGER NOT NULL DEFAULT 1"
)

# Only priced, non-kit-child rows whose qty already had the pack folded in.
BACKFILL = """
UPDATE order_item
   SET units_per_item = qty
 WHERE qty_is_units = true
   AND qty > 1
   AND unit_price IS NOT NULL
   AND parent_item_id IS NULL
   AND units_per_item = 1
"""


def main():
    app = create_app(os.getenv('FLASK_ENV', 'production'))
    with app.app_context():
        db.session.execute(text(ADD_COLUMN))
        db.session.commit()
        print('units_per_item column applied')

        result = db.session.execute(text(BACKFILL))
        db.session.commit()
        print(f'pack size inferred for {result.rowcount} legacy order item(s)')

        from app.services.cost_service import refresh_all_costs

        scanned, changed = refresh_all_costs()
        db.session.commit()
        print(f'cost re-derived: scanned {scanned} components, {changed} updated')


if __name__ == '__main__':
    main()
