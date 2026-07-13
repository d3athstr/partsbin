"""CLI: web-enrich components missing an image or datasheet"""
import click
from flask.cli import AppGroup

from app.models.component import Component

enrich_cli = AppGroup('enrich', help='Web enrichment (images + datasheets)')


@enrich_cli.command('run')
@click.option('--limit', default=25, help='Max components to enrich this run')
@click.option('--component-id', default=None, type=int, help='Enrich one specific component')
def enrich_run(limit, component_id):
    """Find images/datasheets for components missing them (newest first)"""
    from app.ingest.enrich import enrich_component

    if component_id:
        components = Component.query.filter_by(id=component_id).all()
    else:
        components = (
            Component.query
            .filter((Component.image.is_(None)) | (Component.datasheet_url.is_(None)))
            .order_by(Component.id.desc())
            .limit(limit)
            .all()
        )

    click.echo(f'{len(components)} component(s) to enrich')
    got_image = got_ds = 0
    for component in components:
        try:
            result = enrich_component(component.id)
        except Exception as e:
            click.echo(f'  #{component.id} {component.name[:50]}: ERROR {e}')
            continue
        got_image += result['image']
        got_ds += result['datasheet']
        click.echo(
            f'  #{component.id} {component.name[:50]}: '
            f'image={"+" if result["image"] else "-"} '
            f'datasheet={"+" if result["datasheet"] else "-"}'
        )
    click.echo(f'done: {got_image} images, {got_ds} datasheets attached')


def init_app(app):
    """Register the enrich command group"""
    app.cli.add_command(enrich_cli)
