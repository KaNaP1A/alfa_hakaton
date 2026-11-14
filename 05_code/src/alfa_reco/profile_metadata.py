"""Conservative, source-grounded profile signals; these are not skill labels."""

import re
import unicodedata

STAGES = frozenset({"idea", "launch", "operating", "scaling"})
EXPERIENCE = frozenset({"beginner", "intermediate", "advanced"})


def normalize_label(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


# Narrow, explicit aliases for terms used by the snapshot; no fuzzy matching.
INDUSTRY_ALIASES = {
    "ритейл": "розница",
    "розничная торговля": "розница",
    "e-commerce": "ecom",
    "электронная коммерция": "ecom",
    "интернет-торговля": "ecom",
    "horeca": "horeca",
    "horeсa": "horeca",  # The source contains a Cyrillic letter in this label.
}
NON_INDUSTRY_FACETS = frozenset({"без опыта", "с опытом", "💥 new"})


def normalized_industry(value):
    value = normalize_label(value)
    return INDUSTRY_ALIASES.get(value, value)


def industry_matches(value, item):
    if not value:
        return False
    requested = normalized_industry(value)
    if requested in NON_INDUSTRY_FACETS:
        return False
    return any(
        normalize_label(facet) not in NON_INDUSTRY_FACETS
        and normalized_industry(facet) == requested
        for facet in item.get("industries", [])
    )


def experience_evidence(experience, item):
    """Map explicit source facets to business experience, not topic mastery."""
    if not experience:
        return None
    facets = {normalize_label(value) for value in item.get("industries", [])}
    labels = facets & {"без опыта", "с опытом"}
    if len(labels) != 1:
        return None
    label = next(iter(labels))
    matches = (experience == "beginner" and label == "без опыта") or (
        experience in {"intermediate", "advanced"} and label == "с опытом"
    )
    if not matches:
        return None
    return {"source": "industries", "facet": label, "interpretation": "business_experience_hint"}


def stage_evidence(stage, item):
    """Recognize one narrow explicit formulation; all other texts stay unknown."""
    if stage != "launch" or item.get("kind") != "course" or item.get("source_table") != "Courses":
        return None
    audience = normalize_label(item.get("target_audience") or "").rstrip(" .!?")
    if not re.fullmatch(r"(?:вы )?только начинаете (?:свой )?бизнес", audience):
        return None
    return {"source": "target_audience", "rule": "explicit_starting_business", "stage": "launch"}
