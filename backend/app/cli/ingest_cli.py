"""Ingestion CLI commands.

Usage:
    flask ingest run             # one polling + parsing pass (30-min timer)
    flask ingest status          # per-account token/poll status
    flask ingest token-monitor   # keep-alive refresh + dead-grant emails (6h timer)
    flask ingest amazon-details  # recover items Amazon redacts out of its email
"""
import json

import click
from flask.cli import AppGroup, with_appcontext

ingest_cli = AppGroup('ingest', help='Order-email ingestion pipeline commands')


@ingest_cli.command('run')
@click.option('--account', default=None, help='Only poll one account')
@with_appcontext
def ingest_run(account):
    """Poll Gmail accounts, parse new order emails, upsert orders."""
    from app.ingest.pipeline import run_ingest

    accounts = [account] if account else None
    summary = run_ingest(accounts=accounts)
    click.echo(json.dumps(summary, indent=2))


@ingest_cli.command('amazon-details')
@click.option('--limit', default=None, type=int, help='Max orders to process this run')
@click.option('--order', 'order_no', default=None, help='Just this vendor order number')
@click.option('--account', default=None, help='Only orders for one gmail account')
@click.option('--since', default=None, help='Only orders on/after this date (YYYY-MM-DD)')
@click.option('--include-ignored', is_flag=True,
              help='Also fetch orders auto-ignored as non-inventory')
@click.option('--dry-run', is_flag=True, help='Show what would be imported, write nothing')
@with_appcontext
def amazon_details_command(limit, order_no, account, since, include_ignored, dry_run):
    """Recover item detail Amazon redacts out of its order emails.

    Since ~2026-07-15 Amazon confirmations name no items ("Ordered: 5
    Electronics items"), so orders ingest as a correct shell - number, date,
    total - with nothing on them. This fetches each such order's details page
    using the stored browser session and fills the items in.

    Needs a live session: scripts/amazon_session.py check
    """
    from app.ingest.amazon_orders import backfill

    results = backfill(limit=limit, order_no=order_no, account=account,
                       since=since, include_ignored=include_ignored,
                       dry_run=dry_run, log=click.echo)
    imported = sum(r.get('created', 0) for r in results)
    click.echo(f'\n{len(results)} order(s) processed, {imported} item(s) imported')


@ingest_cli.command('status')
@with_appcontext
def ingest_status_command():
    """Show per-account token health, last poll and counts."""
    from app.ingest.pipeline import ingest_status

    click.echo(json.dumps(ingest_status(), indent=2))


@ingest_cli.command('token-monitor')
@with_appcontext
def token_monitor_command():
    """Keep-alive refresh of all Google tokens; email re-auth links for dead grants."""
    from app.ingest.token_monitor import run_token_monitor

    click.echo(json.dumps(run_token_monitor(), indent=2))


def init_app(app):
    """Register the ingest command group"""
    app.cli.add_command(ingest_cli)
