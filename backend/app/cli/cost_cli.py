"""CLI: rebuild actual component costs and fill in missing estimates"""
import click
from flask.cli import AppGroup

from app import db
from app.models.component import Component

cost_cli = AppGroup('cost', help='Component cost tracking (actual + estimated)')


@cost_cli.command('backfill')
def cost_backfill():
    """Re-derive every component's actual unit cost from its order history.

    Safe to re-run: it rebuilds the denormalized last_cost_* fields from the
    order ledger, so it also repairs drift.
    """
    from app.services.cost_service import refresh_all_costs

    scanned, changed = refresh_all_costs()
    db.session.commit()

    priced = Component.query.filter(Component.last_unit_cost.isnot(None)).count()
    click.echo(f'scanned {scanned} components, updated {changed}')
    click.echo(f'{priced} of {scanned} now have an actual unit cost from purchase history')


@cost_cli.command('estimate')
@click.option('--limit', default=25, help='Max components to price this run')
@click.option('--component-id', default=None, type=int, help='Price one specific component')
@click.option('--force', is_flag=True, help='Replace estimates that already exist')
@click.option('--projects-only', is_flag=True,
              help='Only components that appear on a project BOM')
@click.option('--dry-run', is_flag=True, help='List what would be priced, call nothing')
def cost_estimate(limit, component_id, force, projects_only, dry_run):
    """Web-search estimated prices for components that have no price at all.

    Skips anything with a real purchase price - an actual beats a guess.
    """
    from app.ingest.enrich import estimate_price
    from app.models.project import ProjectComponent

    if component_id:
        components = Component.query.filter_by(id=component_id).all()
    else:
        query = Component.query.filter(Component.last_unit_cost.is_(None))
        if not force:
            query = query.filter(Component.est_unit_cost.is_(None))
        if projects_only:
            query = query.filter(Component.id.in_(
                db.session.query(ProjectComponent.component_id)
            ))
        components = query.order_by(Component.id.desc()).limit(limit).all()

    if dry_run:
        click.echo(f'{len(components)} component(s) would be priced:')
        for component in components:
            click.echo(f'  #{component.id} {component.name[:60]}')
        return

    click.echo(f'{len(components)} component(s) to price')
    priced = 0
    for component in components:
        if component.est_unit_cost is not None and not force and not component_id:
            continue
        try:
            result = estimate_price(component)
        except Exception as e:
            click.echo(f'  #{component.id} {component.name[:50]}: ERROR {e}')
            db.session.rollback()
            continue
        if result is None:
            click.echo(f'  #{component.id} {component.name[:50]}: no credible price found')
            continue
        db.session.commit()
        priced += 1
        click.echo(
            f'  #{component.id} {component.name[:50]}: '
            f'${result["unit_price"]} ({result.get("note") or result.get("vendor") or "web"})'
        )
    click.echo(f'done: {priced} estimate(s) written')


def init_app(app):
    """Register the cost command group"""
    app.cli.add_command(cost_cli)
