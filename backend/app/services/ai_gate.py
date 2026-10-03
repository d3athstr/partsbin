"""Once-per-item gate for paid Claude web lookups (enrich / price / lookup).

Rule (Don, 2026-10-03): each component gets ONE automatic attempt per kind.
After that, a further attempt only happens when a person explicitly asks for it
- the UI buttons send manual=true, and CLI commands that name a single
--component-id count as manual. Background paths (nightly sweep, enrichment
after order auto-create, MCP/API callers that don't say manual) are refused.

A call that raises is NOT recorded: an API error is not an attempt, so it does
not burn the item's one automatic try.
"""
from datetime import datetime

from app import db
from app.models.ai_attempt import AiAttempt

KINDS = ('enrich', 'price', 'lookup')
LABELS = {'enrich': 'enrichment', 'price': 'price estimate', 'lookup': 'part lookup'}


def get(component_id, kind):
    return db.session.get(AiAttempt, (component_id, kind))


def blocked(component_id, kind, manual):
    """None when the attempt may run, else a human-readable refusal."""
    assert kind in KINDS, kind
    if manual:
        return None
    prior = get(component_id, kind)
    if prior is None:
        return None
    when = prior.last_at.strftime('%Y-%m-%d') if prior.last_at else 'earlier'
    return (f'Automatic {LABELS[kind]} already ran for this component ({when}). '
            f'Further attempts must be run manually from the PartsBin UI.')


def record(component_id, kind, manual):
    """Record a completed attempt (success or empty result). Commits."""
    now = datetime.utcnow()
    row = get(component_id, kind)
    if row is None:
        row = AiAttempt(component_id=component_id, kind=kind, first_at=now,
                        last_at=now, count=1)
        db.session.add(row)
    else:
        row.last_at = now
        row.count = (row.count or 0) + 1
    row.last_source = 'manual' if manual else 'auto'
    db.session.commit()
    return row
