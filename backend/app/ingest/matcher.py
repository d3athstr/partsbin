"""Fuzzy matching of parsed order-item titles to existing components"""
from rapidfuzz import fuzz, process, utils

from app.models.component import Component

MATCH_THRESHOLD = 82        # good enough to SUGGEST (human confirms)
AUTO_CONFIRM_THRESHOLD = 92  # strong enough to auto-confirm without a human


def _choices(components):
    """Build {component_id: 'name mpn manufacturer'} candidate strings"""
    return {
        c.id: ' '.join(filter(None, (c.name, c.mpn, c.manufacturer)))
        for c in components
    }


def best_match(title, components=None):
    """Best (component_id, score) for a title, or (None, 0). No threshold."""
    if not title:
        return None, 0
    if components is None:
        components = Component.query.all()
    if not components:
        return None, 0
    result = process.extractOne(
        title, _choices(components),
        scorer=fuzz.token_set_ratio,
        processor=utils.default_process,  # strip punctuation: "(N16R8)" == "N16R8"
    )
    if not result:
        return None, 0
    _, score, component_id = result
    # token_set_ratio scores 100 whenever the component tokens are a subset of
    # the title; a very short generic name ("LED") would match everything, so
    # subset-perfect scores only count as auto-confirmable with >= 3 tokens.
    component = next(c for c in components if c.id == component_id)
    name_tokens = len(utils.default_process(component.name).split())
    if score >= AUTO_CONFIRM_THRESHOLD and name_tokens < 3:
        score = AUTO_CONFIRM_THRESHOLD - 1
    return component_id, score


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
    component_id, score = best_match(title, components=components)
    return component_id if score >= MATCH_THRESHOLD else None
