"""Ingestion CLI commands.

Usage:
    flask ingest run             # one polling + parsing pass (30-min timer)
    flask ingest status          # per-account token/poll status
    flask ingest token-monitor   # keep-alive refresh + dead-grant emails (6h timer)
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
