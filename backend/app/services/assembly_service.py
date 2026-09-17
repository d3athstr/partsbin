"""Assembly-order checking: does the solder order put a contact out of reach?

The failure this exists to stop is mechanical, not electrical. Solder a XIAO
flat onto its carrier and the BAT+/BAT- pads on its underside are gone - the
board works, the battery can never be attached, and nothing about the schematic
or the BOM said so. Written as prose in a README, the ordering constraint is
invisible until it has already been violated.

So an assembly step carries two tag lists alongside its text:

    obstructs     contacts this step puts out of reach once it is done
    needs_access  contacts that must still be reachable to perform this step

and the order is checked MECHANICALLY: a step needing a tag that an earlier
step obstructs is a conflict, reported with both step numbers. Components carry
the same vocabulary in Component.access_tags, so a hazard is recorded once on
the part and warns in every project whose BOM uses it.

Tags are normalised to a strict [a-z0-9-] slug and compared by EXACT equality.
That is deliberate. PartsBin has already been bitten by fuzzy matching - a
630-piece capacitor kit whose 24 values all fuzzy-matched onto one component
because they shared a name suffix - and a near-miss here would either invent a
conflict that is not real or, worse, silently miss one. An unmatched tag is
visible (it warns as unaddressed); a mis-matched tag is not.
"""
import re

# Tag hygiene. Long enough for 'xiao-underside-bat-pads', short enough that the
# UI can render a row of them; capped in count so a paste accident cannot turn
# one step into a hundred tags.
MAX_TAG_LENGTH = 60
MAX_TAGS = 24

_SEPARATORS = re.compile(r'[\s_/,.]+')
_ILLEGAL = re.compile(r'[^a-z0-9-]+')
_DASHES = re.compile(r'-{2,}')
_STRING_SPLIT = re.compile(r'[,;\n]+')


def normalise_tag(value):
    """Reduce one tag to a comparable slug, or None if nothing survives.

    'XIAO Underside' / 'xiao_underside' / 'xiao/underside' all become
    'xiao-underside' so that a tag typed on a component and a tag typed on a
    step three months later still compare equal.
    """
    if not isinstance(value, str):
        return None
    slug = _SEPARATORS.sub('-', value.strip().lower())
    slug = _ILLEGAL.sub('', slug)
    slug = _DASHES.sub('-', slug).strip('-')
    return slug[:MAX_TAG_LENGTH] or None


def normalise_tags(values):
    """Normalise a list of tags, dropping blanks and duplicates, order kept."""
    if values is None:
        return []
    if isinstance(values, str):
        # Accept a comma- or newline-separated string: the MCP tools and the
        # form both find that easier to produce than a JSON array. Split on
        # those two ONLY - splitting on spaces as well turned "C1 pads" into
        # two tags, neither of which matched anything.
        values = _STRING_SPLIT.split(values)
    if not isinstance(values, (list, tuple)):
        raise ValueError('tags must be a list of strings')

    out = []
    for value in values:
        slug = normalise_tag(value)
        if slug and slug not in out:
            out.append(slug)
    if len(out) > MAX_TAGS:
        raise ValueError(f'at most {MAX_TAGS} tags per field')
    return out


def _step_label(step):
    return f'step {step.seq}'


def check_steps(steps):
    """Find steps that need access to something an earlier step obstructed.

    Walks the steps in order keeping, for each obstructed tag, the FIRST step
    that obstructed it - that is the step a conflict has to move relative to,
    and naming a later one would send you editing the wrong line.

    A step's own obstructs are applied only AFTER its needs_access is checked,
    because a step is allowed to be the thing that closes the access it used:
    'mount the XIAO' needs the underside reachable and is exactly what makes it
    unreachable. That is the normal case, not a conflict.
    """
    conflicts = []
    obstructed = {}  # tag -> step that first obstructed it

    for step in steps:
        for tag in (step.needs_access or []):
            blocker = obstructed.get(tag)
            if blocker is not None:
                conflicts.append({
                    'tag': tag,
                    'step_id': step.id,
                    'step_seq': step.seq,
                    'step_title': step.title,
                    'blocked_by_id': blocker.id,
                    'blocked_by_seq': blocker.seq,
                    'blocked_by_title': blocker.title,
                    'message': (
                        f'Step {step.seq} ("{step.title}") needs access to '
                        f'"{tag}", which step {blocker.seq} '
                        f'("{blocker.title}") puts out of reach. '
                        f'Do step {step.seq} before step {blocker.seq}.'
                    ),
                })
        for tag in (step.obstructs or []):
            obstructed.setdefault(tag, step)

    return conflicts


def check_bom_hazards(steps, bom_lines):
    """Warn about BOM parts whose recorded access hazard no step addresses.

    A part with access_tags is one that is known to hide a contact. If no step
    declares it needs that access, either the step is missing or the hazard was
    never considered - both worth saying out loud. This is the half of the
    check that fires on a project whose steps were written without the part in
    mind, which is precisely the case a conflict check alone cannot see.
    """
    addressed = set()
    for step in steps:
        addressed.update(step.needs_access or [])
        addressed.update(step.obstructs or [])

    hazards = []
    for line in bom_lines:
        component = line.component
        if component is None:
            continue
        tags = component.access_tags or []
        if not tags:
            continue
        missing = [t for t in tags if t not in addressed]
        hazards.append({
            'component_id': component.id,
            'component_name': component.name,
            'access_tags': tags,
            'unaddressed_tags': missing,
            'assembly_notes': component.assembly_notes,
            'addressed': not missing,
            'message': (
                f'"{component.name}" hides {_join(missing)} once mounted, and no '
                f'assembly step mentions {"it" if len(missing) == 1 else "them"}.'
                if missing else
                f'"{component.name}" hides {_join(tags)}; the assembly order accounts for '
                f'{"it" if len(tags) == 1 else "them"}.'
            ),
        })
    return hazards


def _join(tags):
    """'a', 'a and b', 'a, b and c' - read aloud in a warning."""
    quoted = [f'"{t}"' for t in tags]
    if len(quoted) <= 1:
        return quoted[0] if quoted else ''
    return f'{", ".join(quoted[:-1])} and {quoted[-1]}'


def assembly_report(steps, bom_lines):
    """Full assembly picture for one project: steps, conflicts, hazards, status.

    status is the ISA-101 exception level the UI colours from:
      'conflict' - the recorded order is wrong and will strand a contact (red)
      'warning'  - a known hazard is unaddressed, or there is no order at all
                   for a build that has one (amber)
      'ok'       - checked and clean (gray - no green pill)
      'none'     - nothing to say: no steps and no hazardous parts
    """
    steps = sorted(steps, key=lambda s: (s.seq, s.id))
    conflicts = check_steps(steps)
    hazards = check_bom_hazards(steps, bom_lines)
    unaddressed = [h for h in hazards if not h['addressed']]

    if conflicts:
        status = 'conflict'
    elif unaddressed:
        status = 'warning'
    elif steps:
        status = 'ok'
    else:
        status = 'none'

    return {
        'steps': [s.to_dict() for s in steps],
        'step_count': len(steps),
        'steps_done': sum(1 for s in steps if s.done),
        'conflicts': conflicts,
        'hazards': hazards,
        'unaddressed_hazard_count': len(unaddressed),
        'status': status,
    }


def resequence(steps):
    """Renumber steps 1..N in their current order.

    Sequence numbers are normalised on every mutation rather than being held
    unique by the database, so an insert or a reorder is one pass with no
    temporary values and no constraint to dance around.
    """
    for index, step in enumerate(sorted(steps, key=lambda s: (s.seq, s.id)), start=1):
        if step.seq != index:
            step.seq = index
