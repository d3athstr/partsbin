"""Fuzzy matching of parsed order-item titles to existing components"""
import re

from rapidfuzz import fuzz, process, utils

# ESP32-style flash/PSRAM variant codes (N16R8, N8R2, ...): same-family boards
# that must never cross-match - a different code means a different part.
VARIANT_CODE = re.compile(r'\bN\d+R\d+\b', re.IGNORECASE)

# Amazon redacts order confirmations to "Ordered: 5 Electronics items", and the
# parser used to emit one line per category as a placeholder title: "Hardware
# item", "Pet item", "Electronics item". These name a DEPARTMENT, not a part.
#
# They are poison to every downstream step. On 2026-07-22 "Hardware item" was
# run through auto-create, where Claude inferred a plausible-sounding component
# definition out of nothing and the result fuzzy-matched component 210
# (SS34 / 1N5822 Schottky Diode) at the 82 SUGGEST bar - which auto-create then
# marks 'confirmed' with no human ever seeing it. The order auto-received two
# days later and put a phantom unit into stock at $6.56, roughly 10x what a 3A
# Schottky costs.
#
# Matching the whole string (not a substring) keeps real parts safe: a genuine
# title carries a manufacturer, a value, a package or a part number somewhere,
# so it cannot be only category words followed by "item".
# The leading \d* matters: Amazon phrases these with a count ("2 Electronics
# items"), and without it the guard leaks on exactly the multi-item orders that
# carry the least information.
PLACEHOLDER_TITLE = re.compile(r'^\d*\s*[a-z&,\sà-ÿ]+ items?$', re.IGNORECASE)


def is_placeholder_title(title):
    """True for a redacted category-noun title that identifies no actual part.

    Deliberately narrow. A broad "looks too generic" heuristic would reject
    legitimately terse inventory names like "Wire Mesh Screen", so this only
    catches the specific shape a redacted vendor email produces.
    """
    return bool(PLACEHOLDER_TITLE.match((title or '').strip()))


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
    # A department name can never identify a part. Refusing here covers every
    # caller at once - ingest auto-confirm, suggestions, and the auto-create
    # dedupe lookup that caused the phantom stock movement.
    if is_placeholder_title(title):
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
    # Auto-confirm demands the title carry EVERY distinguishing token of the
    # component name (hyphen-collapsed). A generic title like "ESP32
    # Development Board" is a strict subset of "ESP32-S3 Development Board
    # (N16R8, USB-C)" and token_set_ratio scores subsets 100 - it may be a
    # suggestion for a human, never an unattended stock movement.
    name_set = set(utils.default_process(component.name.replace('-', '')).split())
    title_set = set(collapsed_title.split())
    if not name_set <= title_set:
        score = min(score, AUTO_CONFIRM_THRESHOLD - 1)
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
