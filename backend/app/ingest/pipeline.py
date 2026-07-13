"""Ingestion pipeline: poll Gmail, parse with Claude, upsert orders.

Orders are upserted by (vendor, order_no, gmail_account):
  - "ordered" events create the order + items (with fuzzy match suggestions)
  - "shipped"/"delivered" events only upgrade status / tracking
Nothing here ever touches component stock - receipt is a human action in the
review queue (POST /api/orders/<id>/receive).
"""
from datetime import datetime, date
from email.utils import parsedate_to_datetime

from flask import current_app

from app import db
from app.models.order import Order, OrderItem, STATUS_RANK
from app.models.processed_message import ProcessedMessage
from app.models.component import Component
from app.ingest import gmail_client
from app.ingest.matcher import best_match, MATCH_THRESHOLD, AUTO_CONFIRM_THRESHOLD


def _message_date(message):
    """The email's own Date header as a date (None if unparseable)"""
    try:
        return parsedate_to_datetime(message.get('date')).date()
    except Exception:
        return None


def _upsert_order(account, message, parsed):
    """Create or update an Order from a parsed order email. Returns the Order."""
    vendor = parsed['vendor']
    order_no = parsed['order_no']
    event = parsed['event'] or 'ordered'

    order = None
    if order_no:
        order = Order.query.filter_by(
            vendor=vendor, vendor_order_no=order_no, gmail_account=account,
        ).first()
    elif parsed.get('tracking'):
        # Number-less carrier-status emails can still join their order by
        # tracking number
        order = Order.query.filter_by(
            vendor=vendor, tracking_no=parsed['tracking'], gmail_account=account,
        ).first()

    if order is None and not order_no and event in ('shipped', 'delivered'):
        # Tracking-status noise: the real order always arrives with a number
        # in its confirmation email. Creating a numberless twin here is how
        # stock gets counted twice - drop it.
        return None

    if order is None:
        order = Order(
            vendor=vendor,
            vendor_order_no=order_no,
            status=event,
            order_date=_message_date(message) or date.today(),
            gmail_account=account,
            gmail_message_ids=[message['id']],
            raw_subject=(message.get('subject') or '')[:300],
            tracking_no=parsed.get('tracking'),
            carrier=parsed.get('carrier'),
        )
        db.session.add(order)
        db.session.flush()

        components = Component.query.all()
        for item_data in parsed['items']:
            units = item_data.get('units_per_item', 1)
            item = OrderItem(
                order_id=order.id,
                raw_title=item_data['title'],
                qty=item_data['qty'] * units,
                qty_is_units=True,
                unit_price=item_data.get('unit_price'),
            )
            if not item_data.get('is_component', True):
                # Dog treats et al: never part of inventory, never reviewed
                item.match_status = 'ignored'
                db.session.add(item)
                continue
            match_id, score = best_match(item_data['title'], components=components)
            if match_id and score >= AUTO_CONFIRM_THRESHOLD:
                # Strong match to an existing component: no human needed
                item.component_id = match_id
                item.match_status = 'confirmed'
            elif match_id and score >= MATCH_THRESHOLD:
                item.suggested_component_id = match_id
                item.match_status = 'suggested'
            db.session.add(item)

        # An order with nothing inventory-relevant on it disappears entirely
        if parsed['items'] and all(
            not it.get('is_component', True) for it in parsed['items']
        ):
            order.status = 'ignored'
            order.notes = 'auto-ignored: no electronics/maker items'.strip()
    else:
        # Status only ever moves forward, and receipt stays a human action
        if (order.status != 'received'
                and STATUS_RANK.get(event, 0) > STATUS_RANK.get(order.status, 0)):
            order.status = event
        if parsed.get('tracking'):
            order.tracking_no = parsed['tracking']
        if parsed.get('carrier'):
            order.carrier = parsed['carrier']
        message_ids = list(order.gmail_message_ids or [])
        if message['id'] not in message_ids:
            message_ids.append(message['id'])
            order.gmail_message_ids = message_ids
        # If this email predates the recorded date (e.g. the "ordered" email
        # arrived after a "shipped" one created the order), keep the earliest
        md = _message_date(message)
        if md and (order.order_date is None or md < order.order_date):
            order.order_date = md

    return order


def _maybe_auto_receive(order):
    """Receive a delivered order automatically when every item is resolved.

    Repeat purchases whose items all auto-confirmed against existing
    components flow into stock with no human touch; anything with an
    unmatched/suggested item stays in the review queue.
    """
    from app.services.stock_service import receive_order_items

    if order.status != 'delivered':
        return False
    items = list(order.items)
    if not items:
        return False
    if any(it.match_status not in ('confirmed', 'ignored') for it in items):
        return False

    receive_order_items(
        order, user_id=None,
        note=f'auto-received: {order.vendor} order {order.vendor_order_no or order.id}',
    )
    order.status = 'received'
    order.received_at = datetime.utcnow()
    return True


def run_ingest(accounts=None):
    """Run one ingestion pass across all authorized Gmail accounts.

    Returns a per-account summary list.
    """
    from app.ingest.claude_parser import parse_order_email

    summary = []
    for account in accounts or gmail_client.get_accounts():
        result = {
            'account': account,
            'fetched': 0,
            'orders': 0,
            'non_order': 0,
            'errors': 0,
        }

        if account not in gmail_client.load_tokens():
            result['error'] = 'no token stored'
            summary.append(result)
            continue

        known_ids = {
            row.message_id
            for row in ProcessedMessage.query.filter_by(gmail_account=account)
            .with_entities(ProcessedMessage.message_id)
        }

        try:
            for message in gmail_client.poll_account(account, known_ids):
                result['fetched'] += 1
                try:
                    # Pharmacy mail is excluded from the Gmail query too; this
                    # guard keeps it out of Claude even if the query misses one.
                    sender_l = (message.get('sender') or '').lower()
                    subject_l = (message.get('subject') or '').lower()
                    is_delay_notice = any(k in subject_l for k in (
                        'delay', 'running late', 'arriving late',
                        'delivery date has changed', 'new delivery date',
                    ))
                    if 'pharmacy' in sender_l or 'amazon pharmacy' in subject_l \
                            or is_delay_notice:
                        db.session.add(ProcessedMessage(
                            gmail_account=account,
                            message_id=message['id'],
                            is_order=False,
                        ))
                        db.session.commit()
                        continue

                    parsed = parse_order_email(
                        message['subject'], message['sender'],
                        message['body_text'] or message['body_html'],
                    )

                    processed = ProcessedMessage(
                        gmail_account=account,
                        message_id=message['id'],
                        is_order=bool(parsed and parsed['is_order']),
                    )

                    if parsed and parsed['is_order']:
                        order = _upsert_order(account, message, parsed)
                        if order is not None:
                            processed.order_id = order.id
                            result['orders'] += 1
                            if _maybe_auto_receive(order):
                                result['auto_received'] = result.get('auto_received', 0) + 1
                        else:
                            result['untracked_status'] = result.get('untracked_status', 0) + 1
                    else:
                        result['non_order'] += 1

                    db.session.add(processed)
                    db.session.commit()  # per-message commit keeps the run idempotent
                except Exception as e:
                    db.session.rollback()
                    result['errors'] += 1
                    current_app.logger.error(
                        f'Failed to process message {message["id"]} ({account}): {e}'
                    )

            gmail_client.update_state(
                account,
                last_poll=datetime.utcnow().isoformat(),
                last_error=None,
            )
        except Exception as e:
            current_app.logger.error(f'Ingest poll failed for {account}: {e}')
            gmail_client.update_state(account, last_error=str(e))
            result['error'] = str(e)

        summary.append(result)

    return summary


def ingest_status():
    """Per-account status for /api/ingest/status and the dashboard"""
    tokens = gmail_client.load_tokens()
    state = gmail_client.load_state()

    statuses = []
    for account in gmail_client.get_accounts():
        token = tokens.get(account)
        account_state = state.get(account, {})

        if token is None:
            token_state = 'missing'
        elif account_state.get('last_error') and 'invalid_grant' in str(account_state['last_error']):
            token_state = 'dead'
        elif not token.get('refresh_token'):
            token_state = 'dead'
        else:
            token_state = 'ok'

        processed_query = ProcessedMessage.query.filter_by(gmail_account=account)
        statuses.append({
            'account': account,
            'email': token.get('email') if token else None,
            'token': token_state,
            'authorized_at': token.get('authorized_at') if token else None,
            'last_poll': account_state.get('last_poll'),
            'last_error': account_state.get('last_error'),
            'processed_count': processed_query.count(),
            'order_count': processed_query.filter_by(is_order=True).count(),
        })
    return statuses
