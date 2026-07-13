"""One-off repair after the 2026-07-13 2-year backfill.

1. Re-derive order_date for ingested orders from the earliest Gmail Date
   header among their messages (the first backfill run stamped import day).
2. Delete orders created from Amazon Pharmacy emails (now excluded from the
   Gmail query + pipeline; the first run predates that guard).

Run on the VM:
    cd /opt/partsbin/backend && sudo -u deploy bash -c \
      'set -a; source .env; set +a; venv/bin/python scripts/backfill_repair.py'
"""
from email.utils import parsedate_to_datetime

from app import create_app, db
from app.models.order import Order
from app.ingest.gmail_client import get_credentials, _build_service_from_creds

app = create_app()

with app.app_context():
    # --- 2. pharmacy purge first (no point re-dating them) ---
    pharmacy = Order.query.filter(Order.raw_subject.ilike('%pharmacy%')).all()
    for order in pharmacy:
        db.session.delete(order)  # items cascade
    print(f'pharmacy orders deleted: {len(pharmacy)}')
    db.session.commit()

    # --- 1. date repair ---
    services = {}

    def service_for(account):
        if account not in services:
            services[account] = _build_service_from_creds(get_credentials(account))
        return services[account]

    orders = Order.query.filter(Order.gmail_account.isnot(None)).all()
    fixed = skipped = 0
    for order in orders:
        dates = []
        for mid in (order.gmail_message_ids or []):
            try:
                msg = service_for(order.gmail_account).users().messages().get(
                    userId='me', id=mid, format='metadata',
                    metadataHeaders=['Date'],
                ).execute()
                headers = msg.get('payload', {}).get('headers', [])
                raw = next((h['value'] for h in headers if h['name'].lower() == 'date'), None)
                if raw:
                    dates.append(parsedate_to_datetime(raw).date())
            except Exception as e:
                print(f'  order {order.id} msg {mid}: {e}')
        if dates:
            earliest = min(dates)
            if order.order_date != earliest:
                order.order_date = earliest
                fixed += 1
        else:
            skipped += 1
    db.session.commit()
    print(f'orders date-fixed: {fixed}, unfixable: {skipped}, total scanned: {len(orders)}')
