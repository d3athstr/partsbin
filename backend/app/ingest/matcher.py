"""Fuzzy matching of parsed order-item titles to existing components"""
from rapidfuzz import fuzz, process

from app.models.component import Component

MATCH_THRESHOLD = 82


def _choices(components):
    """Build {component_id: 'name mpn manufacturer'} candidate strings"""
    return {
        c.id: ' '.join(filter(None, (c.name, c.mpn, c.manufacturer)))
        for c in components
    }


def suggest_component(title, components=None):
    """Suggest the best-matching component for an order-item title.

    Args:
        title: raw item title parsed from the email
        components: optional pre-fetched Component list (avoids N queries when
            matching many items in one run)

    Returns:
        int | None: suggested component id when the best score clears the
        threshold (~82, token_set_ratio)
    """
    if not title:
        return None

    if components is None:
        components = Component.query.all()
    if not components:
        return None

    best = process.extractOne(
        title,
        _choices(components),
        scorer=fuzz.token_set_ratio,
        score_cutoff=MATCH_THRESHOLD,
    )
    return best[2] if best else None
