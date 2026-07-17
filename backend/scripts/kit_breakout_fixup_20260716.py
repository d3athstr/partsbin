"""Fixups to the 2026-07-16 kit breakout, per Don (same day).

1. The 07-13 hand-counted 25-ct resistor entries were a SEPARATE order, not
   the ELEGOO kit's bags - the reconciliation withheld 250 ELEGOO resistors
   that physically exist. Add the full ELEGOO counts for those values, incl.
   its 20R bag (listing says 20R; Don's separate 22R stays its own part).
2. #86 3mm LED kit: leave as-is per Don.
3. #85 pre-soldered SMD LEDs (120): split into 5 colors per Don -
   red/orange/green/blue/purple, extras to red (120/5 = 24 each, none left).

Run: cd /opt/partsbin/backend && bash -c \
  'set -a; source .env; set +a; PYTHONPATH=. venv/bin/python scripts/kit_breakout_fixup_20260716.py'
"""
from app import create_app, db
from app.models.component import Component
from app.services.stock_service import adjust_stock

DON = 1
app = create_app()


def add(cid_or_comp, qty, note):
    c = db.session.get(Component, cid_or_comp) if isinstance(cid_or_comp, int) else cid_or_comp
    assert c is not None, cid_or_comp
    adjust_stock(c, qty, 'adjustment', user_id=DON, note=note)
    print(f'  +{qty:>3} -> #{c.id} {c.name} (now {c.qty_on_hand})')


with app.app_context():
    print('== ELEGOO reconciliation reversal (07-13 counts were a separate order) ==')
    N = ('Broken out from kit #136 (ELEGOO 17-value); reconciliation reversed '
         'per Don - the 07-13 hand-count was a separate order')
    for cid in (113, 115, 116, 92, 119, 122, 117, 120, 121):
        add(cid, 25, N)

    c20 = Component(name='20Ω ±1% Metal Film Resistor (1/4W)', category='Resistors',
                    user_id=DON, qty_on_hand=0, min_qty=0,
                    specs={'resistance': '20Ω', 'tolerance': '±1%', 'power_rating': '1/4W',
                           'resistor_type': 'Axial-lead metal film'},
                    description='20Ω axial metal film resistor, 1/4W, ±1% tolerance.',
                    notes='ELEGOO EL-CK-004 low-value bag; some kit revisions label it 22Ω - '
                          'if the bag reads 22Ω, merge into the 22Ω component.')
    db.session.add(c20)
    db.session.flush()
    print(f'  created #{c20.id}  {c20.name}')
    add(c20, 25, 'Broken out from kit #136 (ELEGOO 17-value, 525pcs)')

    kit = db.session.get(Component, 136)
    kit.notes = (kit.notes or '') + (
        '\n2026-07-16 (later): reconciliation REVERSED per Don - the 07-13 hand-counted '
        '25-ct entries were a separate order, so the full 525 ELEGOO pieces were added.')

    print('== #85 SMD LED split (per Don: R/O/G/B/P, extras red; 120/5 = 24 each) ==')
    S = 'Broken out from #85 (pre-soldered SMD LED pack) per Don color counts'
    for color in ('Red', 'Orange', 'Green', 'Blue', 'Purple'):
        c = Component(name=f'Pre-Soldered SMD LED with 30cm Wire Leads ({color})',
                      category='LEDs', user_id=DON, qty_on_hand=0, min_qty=0,
                      specs={'color': color, 'wire_length': '30cm', 'wire_type': 'Micro Litz',
                             'forward_voltage': '3V', 'smd_size_options': '0402/0603/0805/1206'},
                      description=f'Pre-wired {color.lower()} SMD LED on 30cm micro litz leads, 3V.')
        db.session.add(c)
        db.session.flush()
        print(f'  created #{c.id}  {c.name}')
        add(c, 24, S)

    c85 = db.session.get(Component, 85)
    adjust_stock(c85, -c85.qty_on_hand, 'adjustment', user_id=DON,
                 note='Pack broken out into per-color components')
    c85.notes = (c85.notes or '') + (
        '\n2026-07-16: broken out into 5 per-color components (24 each; per Don extras go to red).')
    print(f'  zeroed #85 {c85.name}')

    db.session.commit()
    print('COMMITTED')
