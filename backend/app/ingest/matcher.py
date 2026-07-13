"""Fuzzy matching of parsed order-item titles to existing components"""
import re

from rapidfuzz import fuzz, process, utils

# ESP32-style flash/PSRAM variant codes (N16R8, N8R2, ...): same-family boards
# that must never cross-match - a different code means a different part.
VARIANT_CODE = re.compile(r'\bN\d+R\d+\b', re.IGNORECASE)


def _variant_conflict(title, name):
    """True when title and name both carry variant codes but share none"""
    title_codes = {c.upper() for c in VARIANT_CODE.findall(title or '')}
    name_codes = {c.upper() for c in VARIANT_CODE.findall(name or '')}
    return bool(title_codes) and bool(name_codes) and not (title_codes & name_codes)

from app.models.component import Component

MATCH_THRESHOLD = 82        # good enough to SUGGEST (human confirms)
AUTO_CONFIRM_THRESHOLD = 92  # strong enough to auto-confirm without a human


def _candidate_strings(component):
    """Strings a title may match: bare name, name+mpn+manufacturer, bare mpn.

    Scoring against the bare name matters: enrichment adds manufacturer/mpn
    tokens that a vendor title rarely carries, and folding them into a single
    choice string dilutes token_set_ratio below the auto-confirm bar for
    genuinely identical parts.
    """
    combined = ' '.join(filter(None, (component.name, component.mpn, component.manufacturer)))
    candidates = [component.name]
    if combined != component.name:
        candidates.append(combined)
    if component.mpn:
        candidates.append(component.mpn)
    return candidates


def best_match(title, components=None):
    """Best (component_id, score) for a title, or (None, 0). No threshold."""
    if not title:
        return None, 0
    if components is None:
        components = Component.query.all()
    if not components:
        return None, 0
    processed_title = utils.default_process(title)
    # Vendors write ESP32-C6 / ESP32C6 / ESP32 C6 interchangeably; also score
    # with hyphens collapsed so the spelling doesn't split a load-bearing token
    collapsed_title = utils.default_process(title.replace('-', ''))
    component_id, score, component = None, 0, None
    for c in components:
        c_score = 0
        for cand in _candidate_strings(c):
            c_score = max(
                c_score,
                fuzz.token_set_ratio(processed_title, utils.default_process(cand)),
                fuzz.token_set_ratio(collapsed_title, utils.default_process(cand.replace('-', ''))),
            )
        if c_score > score:
            component_id, score, component = c.id, c_score, c
    if component is None:
        return None, 0
    # token_set_ratio scores 100 whenever the component tokens are a subset of
    # the title; a very short generic name ("LED") would match everything, so
    # subset-perfect scores only count as auto-confirmable with >= 3 tokens.
    name_tokens = len(utils.default_process(component.name).split())
    if score >= AUTO_CONFIRM_THRESHOLD and name_tokens < 3:
        score = AUTO_CONFIRM_THRESHOLD - 1
    # A conflicting N16R8/N8R2-style code is a different board, full stop
    if _variant_conflict(title, component.name):
        score = min(score, MATCH_THRESHOLD - 1)
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
