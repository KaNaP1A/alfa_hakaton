"""Optional, conservative geographic-title hints; not verified coverage or rights."""

import re
from functools import lru_cache


@lru_cache(maxsize=1)
def _analyzer():
    try:
        import pymorphy3
        return pymorphy3.MorphAnalyzer()
    except ImportError:
        return None


@lru_cache(maxsize=4096)
def _geographic_forms(word):
    analyzer = _analyzer()
    if analyzer is None:
        return frozenset()
    return frozenset(
        parsed.normal_form.casefold().replace("ё", "е")
        for parsed in analyzer.parse(word)
        if "Geox" in parsed.tag
    )


def _user_region_forms(value):
    if not value:
        return frozenset()
    # Avoid equating different multi-word regions via one common token.
    match = re.fullmatch(r"\s*(?:(?:г\.|город)\s*)?([А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)?)\s*", value)
    return _geographic_forms(match.group(1)) if match else frozenset()


def geographic_hint(title, user_region=None):
    if _analyzer() is None:
        return {"status": "unavailable", "mentions": [], "verified": False}
    mentions, forms = [], set()
    # Capitalization and a location preposition reduce, but do not eliminate, ambiguity.
    pattern = r"\b(?:[Вв]о?)\s+(?:(?:городе|г\.)\s*)?([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)"
    for match in re.finditer(pattern, title):
        name = match.group(1)
        found = _geographic_forms(name) - {"россия"}
        if found:
            mentions.append(name)
            forms.update(found)
    if not mentions:
        return {"status": "not_detected", "mentions": [], "verified": False}
    requested = _user_region_forms(user_region)
    if requested & forms:
        status = "possible_match"
    elif user_region and requested:
        status = "possible_other_region"
    else:
        status = "possible_region_unknown"
    return {"status": status, "mentions": list(dict.fromkeys(mentions)), "verified": False}
