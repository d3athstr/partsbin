"""CLI: web-enrich components missing an image, datasheet or dimensions"""
import json
import os
from datetime import datetime, timedelta

import click
from flask.cli import AppGroup

from app.models.component import Component

enrich_cli = AppGroup('enrich', help='Web enrichment (images + datasheets)')

# Categories whose parts live in standard packages KiCad already ships a
# footprint for. Enrichment is told to report `package` and stop for these, so
# absent dim_* keys are the CORRECT answer and must not make a part look
# perpetually incomplete.
STANDARD_PACKAGE_CATEGORIES = (
    'Resistors', 'Capacitors', 'Diodes', 'LEDs', 'Transistors & MOSFETs', 'ICs',
)

# Where the nightly sweep remembers what it has already tried. Not in the DB:
# this is scheduler bookkeeping, not inventory data, and it must not show up as
# specs on the component page.
STATE_PATH = os.environ.get('ENRICH_STATE_PATH',
                            '/var/lib/partsbin/enrich-state.json')

# A part nobody publishes a drawing for (unbranded modules, hand-made cables)
# will never enrich, no matter how often it is asked. After this many empty
# attempts it drops to the slow lane rather than burning a Claude web-search
# call every single night.
MISS_LIMIT = 4
COLD_RETRY_DAYS = 30


def _load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f, indent=1, sort_keys=True)
    os.replace(tmp, STATE_PATH)  # never leave a half-written state file


def _wants(component):
    """What this component is still missing, as a list of labels."""
    missing = []
    if not component.image:
        missing.append('image')
    if not component.datasheet_url:
        missing.append('datasheet')
    if component.category not in STANDARD_PACKAGE_CATEGORIES:
        specs = component.specs or {}
        if not any(k.startswith('dim_') for k in specs):
            missing.append('dimensions')
    return missing


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


@enrich_cli.command('nightly')
@click.option('--limit', default=15, help='Max components to enrich this run')
@click.option('--dry-run', is_flag=True, help='List what would be enriched, call nothing')
def enrich_nightly(limit, dry_run):
    """Sweep for anything still missing an image, datasheet or dimensions.

    Ordered least-recently-attempted first, so genuinely new components are
    always picked up before anything is retried, and the retry cost is bounded
    by --limit no matter how many hopeless parts the catalogue accumulates.

    `enrich run` only looks at image/datasheet, and enrich_component() skips
    entirely when both are set — so a part with both but no dimensions would
    never be revisited by it. This is the sweep that catches those.
    """
    from app.ingest.enrich import enrich_component

    state = _load_state()
    now = datetime.utcnow()
    cold_before = now - timedelta(days=COLD_RETRY_DAYS)

    candidates = []
    slow_lane = 0
    for component in Component.query.order_by(Component.id).all():
        missing = _wants(component)
        if not missing:
            continue
        entry = state.get(str(component.id)) or {}
        misses = int(entry.get('misses') or 0)
        last_raw = entry.get('last')
        try:
            last = datetime.fromisoformat(last_raw) if last_raw else None
        except ValueError:
            last = None
        # Parts nobody publishes data for drop to the slow lane instead of
        # costing a web search every night forever.
        if misses >= MISS_LIMIT and last and last > cold_before:
            slow_lane += 1
            continue
        candidates.append((last or datetime.min, component, missing))

    candidates.sort(key=lambda c: c[0])
    batch = candidates[:limit]

    click.echo(f'{len(candidates)} component(s) incomplete, {slow_lane} in the '
               f'slow lane (>={MISS_LIMIT} empty tries, retried every '
               f'{COLD_RETRY_DAYS}d); enriching {len(batch)}')
    if dry_run:
        for _, component, missing in batch:
            click.echo(f'  would try #{component.id} {component.name[:44]} '
                       f'-- missing {", ".join(missing)}')
        return

    filled = failed = 0
    for _, component, missing in batch:
        try:
            # force=True: the default skips when image+datasheet are both set,
            # which would silently exclude every dimensions-only gap.
            result = enrich_component(component.id, force=True)
        except Exception as e:
            failed += 1
            click.echo(f'  #{component.id} {component.name[:44]}: ERROR '
                       f'{type(e).__name__} {str(e)[:80]}')
            # An error is not evidence the part is unenrichable, so it does not
            # count as a miss - only a clean empty result does.
            continue

        still = _wants(component)
        gained = [m for m in missing if m not in still]
        entry = state.setdefault(str(component.id), {})
        entry['last'] = now.isoformat(timespec='seconds')
        entry['misses'] = 0 if gained else int(entry.get('misses') or 0) + 1
        entry['name'] = component.name[:60]
        entry['missing'] = still
        if gained:
            filled += 1
            click.echo(f'  #{component.id} {component.name[:44]}: '
                       f'+{", +".join(gained)}')
        else:
            click.echo(f'  #{component.id} {component.name[:44]}: nothing found '
                       f'(miss {entry["misses"]}/{MISS_LIMIT})')

    _save_state(state)
    click.echo(f'done: {filled} improved, {len(batch) - filled - failed} empty, '
               f'{failed} error(s)')
    if failed:
        raise SystemExit(1)  # the wrapper turns a non-zero exit into a Prowl alert


def init_app(app):
    """Register the enrich command group"""
    app.cli.add_command(enrich_cli)
