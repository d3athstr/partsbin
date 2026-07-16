"""Break out assortment/kit components into individual components (2026-07-16).

Per Don: packs of varying items (e.g. a box of resistors of varying ohms)
become individual components with real per-value quantities.

Kits broken out:
  #4   DB9 Male/Female Solder Cup Connector Kit      -> male / female / hoods
  #51  WayinTop Resistor & LED Assortment Kit        -> 30 resistor values x20 + 5 LED colors x40
  #136 ELEGOO 17-Value 1% Resistor Kit (525pcs)      -> per-value, RECONCILED against Don's
       07-13 hand-counted 25-ct entries (those were almost certainly this kit's bags:
       all are exactly 25 at ELEGOO-specific values like 0R and 470k)
  (+ more kits appended by later sections)

Run on the VM:
    cd /opt/partsbin/backend && bash -c \
      'set -a; source .env; set +a; PYTHONPATH=. venv/bin/python scripts/kit_breakout_20260716.py'
"""
from app import create_app, db
from app.models.component import Component
from app.services.stock_service import adjust_stock

DON = 1
app = create_app()
created = []


def get(cid):
    c = db.session.get(Component, cid)
    assert c is not None, f'component {cid} missing'
    return c


def create(name, category, specs=None, manufacturer=None, description=None, notes=None):
    c = Component(name=name, category=category, user_id=DON, qty_on_hand=0,
                  min_qty=0, specs=specs or {}, manufacturer=manufacturer,
                  description=description, notes=notes)
    db.session.add(c)
    db.session.flush()
    created.append((c.id, name))
    print(f'  created #{c.id}  {name}')
    return c


def add(comp, qty, note):
    if qty <= 0:
        return
    adjust_stock(comp, qty, 'adjustment', user_id=DON, note=note)
    print(f'  +{qty:>3} -> #{comp.id} {comp.name} (now {comp.qty_on_hand})')


def zero(cid, note_line):
    c = get(cid)
    if c.qty_on_hand:
        adjust_stock(c, -c.qty_on_hand, 'adjustment', user_id=DON,
                     note='Kit contents broken out into individual components')
    c.notes = (((c.notes or '').rstrip() + '\n') if c.notes else '') + note_line
    print(f'  zeroed #{cid} {c.name}')


def resistor(value_label):
    """Create a 1/4W 1% metal film resistor component in the house style."""
    return create(
        f'{value_label} ±1% Metal Film Resistor (1/4W)', 'Resistors',
        specs={'resistance': value_label, 'tolerance': '±1%',
               'power_rating': '1/4W', 'resistor_type': 'Axial-lead metal film'},
        description=f'{value_label} axial metal film resistor, 1/4W, ±1% tolerance.')


with app.app_context():
    # ------------------------------------------------------------------
    # Resistors: ELEGOO #136 (confirmed 13x25 + 100R/220R/1k/10k x50)
    # + WayinTop #51 (confirmed 30 values x20). Existing 25-ct components
    # from 07-13 are treated as the ELEGOO bags already binned.
    # ------------------------------------------------------------------
    print('== Resistors (kits #136 ELEGOO + #51 WayinTop) ==')
    E = 'Broken out from kit #136 (ELEGOO 17-value, 525pcs)'
    ER = E + '; reconciled: 07-13 hand-count was this kit'
    W = 'Broken out from kit #51 (WayinTop Resistor & LED Assortment)'

    # value -> (existing component id or None, elegoo delta, wayintop delta)
    RES = {
        '0Ω':    (113, 0,  0),   # ELEGOO 25 already counted 07-13
        '10Ω':   (115, 0,  20),
        '22Ω':   (118, 0,  20),  # ELEGOO lists 20R in some listings; Don's bag read 22R
        '47Ω':   (116, 0,  20),
        '100Ω':  (92,  25, 20),  # ELEGOO has 50; 25 already counted
        '150Ω':  (None, 0, 20),  # (existing #81 is 1/2W EDGELEC - separate part)
        '200Ω':  (None, 0, 20),
        '220Ω':  (None, 50, 20),
        '270Ω':  (None, 0, 20),
        '330Ω':  (None, 0, 20),  # (existing #16 is 1/2W - separate part)
        '470Ω':  (119, 0,  20),
        '510Ω':  (None, 0, 20),
        '680Ω':  (None, 0, 20),
        '1kΩ':   (122, 25, 20),  # ELEGOO has 50; 25 already counted
        '2kΩ':   (None, 0, 20),
        '2.2kΩ': (117, 0,  20),
        '3.3kΩ': (None, 0, 20),
        '4.7kΩ': (None, 25, 20),
        '5.1kΩ': (None, 0, 20),
        '6.8kΩ': (None, 0, 20),
        '10kΩ':  (None, 50, 20),
        '20kΩ':  (None, 0, 20),
        '22kΩ':  (None, 25, 0),
        '47kΩ':  (None, 25, 20),
        '51kΩ':  (None, 0, 20),
        '68kΩ':  (None, 0, 20),
        '100kΩ': (120, 0,  20),
        '220kΩ': (None, 25, 20),
        '300kΩ': (None, 0, 20),
        '470kΩ': (121, 0,  20),
        '680kΩ': (None, 0, 20),
        '1MΩ':   (None, 25, 20),
    }
    for value, (cid, e_delta, w_delta) in RES.items():
        comp = get(cid) if cid else resistor(value)
        add(comp, e_delta, ER if cid else E)
        add(comp, w_delta, W)

    # WayinTop LEDs: 5mm, 40 each (blue straw-hat #74 is a different part)
    print('== LEDs (kit #51 WayinTop) ==')
    for color in ('Red', 'Green', 'Yellow', 'Blue', 'White'):
        c = create(f'5mm LED ({color})', 'LEDs',
                   specs={'size': '5mm', 'color': color, 'package': 'Through Hole',
                          'max_forward_current': '20mA'},
                   description=f'5mm through-hole {color.lower()} LED.')
        add(c, 40, W)

    zero(51, '2026-07-16: kit broken out into individual resistor values (x20 each) and 5mm LED colors (x40 each).')
    zero(136, "2026-07-16: kit broken out into individual resistor values; Don's 07-13 25-ct entries treated as this kit's bags (verify: 100Ω/1kΩ should have a second unopened bag of 25 each).")

    # ------------------------------------------------------------------
    # #4 DB9 solder-cup kit: 9 male + 9 female + 18 hoods
    # ------------------------------------------------------------------
    print('== DB9 kit #4 ==')
    D = 'Broken out from kit #4 (Tnuocke 18-pack DB9 kit)'
    c = create('DB9 Male Solder Cup Connector (Tin-Plated)', 'Connectors & Headers',
               specs={'pins': '9', 'type': 'DB9 D-SUB', 'gender': 'male',
                      'termination': 'solder cup', 'max_wire_size': '20 AWG'},
               manufacturer='Tnuocke',
               description='9-pin D-SUB male solder cup connector, tin-plated shell.')
    add(c, 9, D)
    c = create('DB9 Female Solder Cup Connector (Tin-Plated)', 'Connectors & Headers',
               specs={'pins': '9', 'type': 'DB9 D-SUB', 'gender': 'female',
                      'termination': 'solder cup', 'max_wire_size': '20 AWG'},
               manufacturer='Tnuocke',
               description='9-pin D-SUB female solder cup connector, tin-plated shell.')
    add(c, 9, D)
    c = create('DB9 Hood Shell with Hardware (Gray Plastic)', 'Connectors & Headers',
               specs={'fits': 'DB9 D-SUB', 'material': 'gray plastic', 'rating': 'UL94V-0'},
               manufacturer='Tnuocke',
               description='Gray plastic backshell hood for DB9 connectors, with screws/hardware.')
    add(c, 18, D)
    zero(4, '2026-07-16: kit broken out into male (9) / female (9) / hoods (18).')

    # ------------------------------------------------------------------
    # #7 AVARBUVO 120pc lever splice kit (confirmed from listing gallery):
    # 48x 2-cond + 32x 3-cond + 18x 5-cond lever nuts + 22x inline 1-in-1-out
    # ------------------------------------------------------------------
    print('== Lever splice kit #7 ==')
    L = 'Broken out from kit #7 (AVARBUVO 120pc lever connector kit)'
    lever_specs = {'wire_gauge': '28-12 AWG', 'rated_current': '32A',
                   'rated_voltage': '250V', 'type': 'push-in lever, tool-free'}
    lever_comps = {}
    for label, gender_note, qty in (
            ('Lever Wire Splice Connector (2-Conductor)', '2-conductor lever nut', 48),
            ('Lever Wire Splice Connector (3-Conductor)', '3-conductor lever nut', 32),
            ('Lever Wire Splice Connector (5-Conductor)', '5-conductor lever nut', 18),
            ('Inline Lever Splice Connector (1-in-1-out)', 'inline butt-splice lever terminal', 22)):
        c = create(label, 'Connectors & Headers', specs=lever_specs,
                   manufacturer='AVARBUVO',
                   description=f'{gender_note}, 28-12 AWG, reusable push-in lever splice.')
        add(c, qty, L)
        lever_comps[label] = c
    zero(7, '2026-07-16: kit broken out: 48x 2-cond, 32x 3-cond, 18x 5-cond, 22x inline 1-in-1-out.')

    # Re-point the PipBoy BOM line (was the whole kit) at the 2-conductor splice
    from app.models.project import ProjectComponent
    pc = db.session.get(ProjectComponent, 8)
    if pc and pc.component_id == 7:
        pc.component_id = lever_comps['Lever Wire Splice Connector (2-Conductor)'].id
        pc.note = ((pc.note or '') + ' [2026-07-16: kit broken out; re-pointed to 2-conductor splice - swap type if the rails need 3/5-cond]')[:300]
        print('  re-pointed PipBoy BOM line 8 to 2-conductor splice')

    # ------------------------------------------------------------------
    # #111 XHF 205pc marine heat shrink (confirmed from listing bullets):
    # 3/32"x70, 1/8"x70, 3/16"x25, 1/4"x15, 5/16"x5, 3/8"x5, 1/2"x10, 3/4"x5
    # ------------------------------------------------------------------
    print('== Heat shrink kit #111 ==')
    H = 'Broken out from kit #111 (XHF 205pc marine heat shrink)'
    for size, qty in (('3/32"', 70), ('1/8"', 70), ('3/16"', 25), ('1/4"', 15),
                      ('5/16"', 5), ('3/8"', 5), ('1/2"', 10), ('3/4"', 5)):
        c = create(f'Heat Shrink Tubing {size} x 3.5" (3:1, Adhesive-Lined, Marine)',
                   'Wire & Cable',
                   specs={'diameter': size, 'piece_length': '3.5 in',
                          'shrink_ratio': '3:1', 'lining': 'adhesive',
                          'grade': 'marine, waterproof', 'colors': 'half red / half black'},
                   manufacturer='XHF',
                   description=f'{size} marine-grade adhesive-lined 3:1 heat shrink, 3.5 inch pieces.')
        add(c, qty, H)
    zero(111, '2026-07-16: kit broken out per size (70/70/25/15/5/5/10/5 from 3/32" to 3/4").')

    # ------------------------------------------------------------------
    # #29 Ktehloy 361pc M3 heat-set insert kit (confirmed from box-lid
    # grid in listing photo): inserts 4/6/8mm, bolts 6-16mm, 100 nuts, 1 tip
    # ------------------------------------------------------------------
    print('== M3 heat-set insert kit #29 ==')
    K = 'Broken out from kit #29 (Ktehloy 361pc M3 insert kit)'
    for name, desc, specs, qty in (
        ('M3 Heat-Set Threaded Insert (M3x4x5mm, Brass)', 'Brass heat-set insert for 3D prints, M3 thread, 4mm long, 5mm OD.', {'thread': 'M3', 'length': '4mm', 'od': '5mm', 'material': 'brass'}, 60),
        ('M3 Heat-Set Threaded Insert (M3x6x5mm, Brass)', 'Brass heat-set insert for 3D prints, M3 thread, 6mm long, 5mm OD.', {'thread': 'M3', 'length': '6mm', 'od': '5mm', 'material': 'brass'}, 40),
        ('M3 Heat-Set Threaded Insert (M3x8x5mm, Brass)', 'Brass heat-set insert for 3D prints, M3 thread, 8mm long, 5mm OD.', {'thread': 'M3', 'length': '8mm', 'od': '5mm', 'material': 'brass'}, 30),
        ('M3x6mm Hex Socket Head Cap Bolt (12.9 Alloy, Black)', 'M3x6mm hex socket head cap screw, grade 12.9 black alloy steel.', {'thread': 'M3', 'length': '6mm', 'head': 'hex socket cap', 'grade': '12.9'}, 50),
        ('M3x8mm Hex Socket Head Cap Bolt (12.9 Alloy, Black)', 'M3x8mm hex socket head cap screw, grade 12.9 black alloy steel.', {'thread': 'M3', 'length': '8mm', 'head': 'hex socket cap', 'grade': '12.9'}, 30),
        ('M3x10mm Hex Socket Head Cap Bolt (12.9 Alloy, Black)', 'M3x10mm hex socket head cap screw, grade 12.9 black alloy steel.', {'thread': 'M3', 'length': '10mm', 'head': 'hex socket cap', 'grade': '12.9'}, 20),
        ('M3x12mm Hex Socket Head Cap Bolt (12.9 Alloy, Black)', 'M3x12mm hex socket head cap screw, grade 12.9 black alloy steel.', {'thread': 'M3', 'length': '12mm', 'head': 'hex socket cap', 'grade': '12.9'}, 20),
        ('M3x16mm Hex Socket Head Cap Bolt (12.9 Alloy, Black)', 'M3x16mm hex socket head cap screw, grade 12.9 black alloy steel.', {'thread': 'M3', 'length': '16mm', 'head': 'hex socket cap', 'grade': '12.9'}, 10),
        ('M3 Hex Nut (Black Steel)', 'M3 hex nut, black steel.', {'thread': 'M3', 'material': 'black steel'}, 100),
        ('Heat-Set Insert Soldering Iron Tip (M3 / 6-32, Dual-Ended)', 'Dual-ended brass heat-set insert installation tip for soldering irons (M3 and 6-32).', {'fits': 'soldering iron', 'sizes': 'M3, 6-32'}, 1),
    ):
        c = create(name, 'Mechanical', specs=specs, manufacturer='Ktehloy', description=desc)
        add(c, qty, K)
    zero(29, '2026-07-16: kit broken out: inserts M3x4/6/8mm (60/40/30), bolts M3x6-16mm (50/30/20/20/10), 100 nuts, 1 install tip.')

    # ------------------------------------------------------------------
    # #32 Csdtylh 280pc M2.5 standoff kit (confirmed from listing
    # "Package Included"): 8 standoff sizes x15, 80 screws, 80 nuts.
    # 10+6mm merges into existing #27 (same part).
    # ------------------------------------------------------------------
    print('== M2.5 standoff kit #32 ==')
    S = 'Broken out from kit #32 (Csdtylh 280pc M2.5 standoff kit)'
    add(get(27), 15, S + '; same part as this component')
    for name, length, gender, qty in (
        ('M2.5x20mm+6mm Brass Hex Standoff (Male-Female)', '20+6mm', 'male-female', 15),
        ('M2.5x15mm+6mm Brass Hex Standoff (Male-Female)', '15+6mm', 'male-female', 15),
        ('M2.5x6mm+6mm Brass Hex Standoff (Male-Female)', '6+6mm', 'male-female', 15),
        ('M2.5x20mm Brass Hex Standoff (Female-Female)', '20mm', 'female-female', 15),
        ('M2.5x15mm Brass Hex Standoff (Female-Female)', '15mm', 'female-female', 15),
        ('M2.5x10mm Brass Hex Standoff (Female-Female)', '10mm', 'female-female', 15),
        ('M2.5x6mm Brass Hex Standoff (Female-Female)', '6mm', 'female-female', 15),
    ):
        c = create(name, 'Mechanical',
                   specs={'thread': 'M2.5', 'length': length, 'type': gender, 'material': 'brass'},
                   manufacturer='Csdtylh',
                   description=f'M2.5 {length} brass hex {gender} standoff.')
        add(c, qty, S)
    c = create('M2.5x6mm Screw', 'Mechanical',
               specs={'thread': 'M2.5', 'length': '6mm'}, manufacturer='Csdtylh',
               description='M2.5x6mm machine screw (standoff kit).')
    add(c, 80, S)
    c = create('M2.5 Hex Nut', 'Mechanical',
               specs={'thread': 'M2.5'}, manufacturer='Csdtylh',
               description='M2.5 hex nut (standoff kit).')
    add(c, 80, S)
    zero(32, '2026-07-16: kit broken out: 8 standoff sizes x15 (10+6mm merged into #27), 80 screws, 80 nuts.')

    # ------------------------------------------------------------------
    # #65 smseace 30pc JST PH2.0 kit (confirmed from listing: "15 * Male
    # Cable, 15 * Female Cable", 2-pin, 100mm, 22AWG silicone).
    # NOTE: the component's old enrichment (Adafruit 4422, 220pc) was wrong.
    # Kept separate from #98/#99 (Adafruit cables) - JST gender naming is
    # too ambiguous to merge across vendors safely.
    # ------------------------------------------------------------------
    print('== JST PH2.0 kit #65 ==')
    J = 'Broken out from kit #65 (smseace 30pc JST PH2.0 pigtail kit)'
    jst_specs = {'pitch': '2.0mm', 'series': 'JST PH', 'pins': '2',
                 'wire_length': '100mm', 'wire_gauge': '22 AWG silicone'}
    jst_comps = {}
    for gender, qty in (('Male', 15), ('Female', 15)):
        c = create(f'JST PH 2.0mm 2-Pin Pigtail Cable, {gender} (100mm, smseace)',
                   'Connectors & Headers',
                   specs=dict(jst_specs, gender=gender.lower()),
                   manufacturer='smseace',
                   description=f'Pre-wired {gender.lower()} JST PH 2.0mm 2-pin pigtail, '
                               '100mm 22AWG silicone leads.')
        add(c, qty, J)
        jst_comps[gender] = c

    # Re-point the Pool Water Level Monitor BOM line (was the whole kit)
    from app.models.project import ProjectComponent as PC65
    pc63 = db.session.get(PC65, 63)
    if pc63 and pc63.component_id == 65:
        pc63.component_id = jst_comps['Female'].id
        pc63.note = ((pc63.note or '') + ' [2026-07-16: kit broken out; re-pointed to female pigtail - swap to male if that is what the build needs]')[:300]
        print('  re-pointed Pool Monitor BOM line 63 to female pigtail')
    kit65 = get(65)
    kit65.manufacturer = 'smseace'
    kit65.mpn = 'B088NFRNZ2'
    kit65.specs = {'pitch': '2.0mm', 'series': 'PH',
                   'contents': '15 male + 15 female 2-pin pre-wired pigtails, 100mm, 22AWG',
                   'note': 'previous enrichment (Adafruit 4422, 220pc housing kit) was wrong'}
    zero(65, '2026-07-16: kit broken out into 15 male + 15 female 2-pin pigtails; '
             'old Adafruit-4422 enrichment was a mismatch, specs corrected.')

    db.session.commit()
    print('\nCOMMITTED. Created components:')
    for cid, name in created:
        print(f'  #{cid}  {name}')
