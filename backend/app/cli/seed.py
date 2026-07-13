"""Seed command: fixed category list + bootstrap admin invitation.

Usage:
    flask seed
"""
import click
from flask.cli import with_appcontext

from app import db
from app.models.category import Category
from app.models.invitation import InvitationCode
from app.models.user import User

# Fixed component category list (DESIGN.md)
CATEGORIES = [
    'Resistors',
    'Capacitors',
    'Inductors',
    'Diodes',
    'LEDs',
    'Transistors & MOSFETs',
    'ICs',
    'Microcontrollers',
    'Dev Boards',
    'Sensors',
    'Displays',
    'Servos & Motors',
    'Motor Drivers',
    'Batteries & Power',
    'Voltage Regulators',
    'Connectors & Headers',
    'Switches & Buttons',
    'Relays',
    'Wire & Cable',
    'Prototyping',
    'RF Modules (WiFi/BLE/LoRa)',
    'Audio',
    'Mechanical',
    'Tools',
    'Other',
]


@click.command('seed')
@with_appcontext
def seed_command():
    """Seed the category list and create the first admin invitation code."""
    added = 0
    for position, name in enumerate(CATEGORIES):
        category = Category.query.filter_by(name=name).first()
        if category:
            category.position = position
        else:
            db.session.add(Category(name=name, position=position))
            added += 1
    db.session.commit()
    click.echo(f'Categories: {added} added, {len(CATEGORIES) - added} already present.')

    # Bootstrap invitation: only when the instance is brand new
    if User.query.count() == 0 and InvitationCode.query.count() == 0:
        invitation = InvitationCode(
            code=InvitationCode.generate_code(),
            created_by_id=None,
            max_uses=1,
            note='Bootstrap admin invitation (flask seed)',
        )
        db.session.add(invitation)
        db.session.commit()
        click.echo('')
        click.echo('First admin invitation code (register with it - the first')
        click.echo('user automatically becomes an approved admin):')
        click.echo('')
        click.echo(f'    {invitation.code}')
        click.echo('')
    else:
        click.echo('Users or invitations already exist - no bootstrap invitation created.')


def init_app(app):
    """Register the seed command"""
    app.cli.add_command(seed_command)
