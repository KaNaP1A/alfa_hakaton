"""Grounded cold-start suggestions; no popularity or outcome inference."""

import hashlib
from collections import Counter

from .eligibility import USER_KINDS
from .geography import geographic_hint
from .personalization import CATEGORIES, facets
from .pricing import price_fact
from .profile_metadata import experience_evidence, industry_matches, stage_evidence
from .promotions import promotion_for
from .text import tokens


def category_facets(category):
    """Avoid treating the broad 'laws' facet alone as evidence of a finance task."""
    values = CATEGORIES[category][1]
    return values - {"Законы"} if category == "finance" else values


def starter_options(catalog, categories=()):
    """Offer a free-text goal and categories with at least one matching snapshot item."""
    available = set()
    for item in catalog:
        if item.get("kind") not in USER_KINDS:
            continue
        available.update(facets(item))
    if categories:
        labels = sorted({label for category in categories for label in category_facets(category)} & available)
        return {
            "question": "Что именно вы хотите сделать? Можно уточнить тему или описать задачу.",
            "allow_goal_text": True,
            "options": [{"focus_facet": label, "label": label} for label in labels],
        }
    return {
        "question": "Какая задача или направление вам интересны?",
        "allow_goal_text": True,
        "options": [
            {"category": name, "label": label}
            for name, (label, _) in CATEGORIES.items()
            if available & category_facets(name)
        ],
    }


def _normalized(value):
    return " ".join((value or "").casefold().split())


def _duplicate_signature(item):
    """Only flag identical nonempty text as possible duplicates, not verified identity."""
    description = _normalized(item.get("description"))
    body = _normalized(item.get("body"))
    if not description or not body:
        return None
    return (
        item["kind"], _normalized(item["title"]), description, body,
        item.get("access_type"),
    )


def _verified_duplicate_signature(item, text_signature):
    provenance = item.get("provenance") or {}
    if (text_signature is None or not item.get("canonical_url")
            or provenance.get("canonical_url") != "manual_public_page_2026-11-12"):
        return None
    return text_signature, item["canonical_url"]


def _text_coverage(matched, text):
    text_terms = set(tokens(text or ""))
    coverages = []
    for label in matched:
        terms = set(tokens(label))
        if terms:
            coverages.append(len(terms & text_terms) / len(terms))
    return max(coverages, default=0.0)


def recommend_cold_start(catalog, profile, limit):
    """Rank candidates grounded in selected catalog facets; profile was validated upstream."""
    selected = {name for category in profile["categories"] for name in category_facets(category)}
    if profile["focus_facet"]:
        selected &= {profile["focus_facet"]}
    options = starter_options(catalog, profile["categories"])
    if not selected:
        return [], options
    candidates = []
    for item in catalog:
        if item.get("kind") not in USER_KINDS:
            continue
        matched = sorted(facets(item) & selected)
        if not matched:
            continue
        title_match = _text_coverage(matched, item["title"])
        description_match = _text_coverage(matched, item.get("description", ""))
        kind_match = item["kind"] in profile["preferred_kinds"]
        industry_match = industry_matches(profile["industry"], item)
        experience = experience_evidence(profile["experience"], item)
        stage = stage_evidence(profile["business_stage"], item)
        geography = geographic_hint(item["title"], profile["region"])
        # Preferences and diversity only break ties in the direct text signals.
        preference = 0.1 * kind_match + 0.1 * industry_match + 0.05 * bool(experience) + 0.05 * bool(stage)
        categories = [name for name in profile["categories"] if facets(item) & category_facets(name)]
        text_signature = _duplicate_signature(item)
        candidates.append({
            "item": item,
            "preference": preference,
            "title_match": title_match,
            "description_match": description_match,
            "facets": set(matched),
            "text_signature": text_signature,
            "verified_signature": _verified_duplicate_signature(item, text_signature),
            "stable_order": (
                _normalized(item["title"]), _normalized(item.get("description")),
                hashlib.sha256(_normalized(item.get("body")).encode("utf-8")).hexdigest(),
                item["kind"], tuple(sorted(item.get("topics", []))),
                tuple(sorted(item.get("tags", []))), tuple(sorted(item.get("industries", []))),
                _normalized(item.get("access_type")), item["entity_key"],
            ),
            "evidence": {
                "matched_facets": matched,
                "categories": categories,
                "title_coverage": round(title_match, 4),
                "description_coverage": round(description_match, 4),
                "preferred_kind": kind_match,
                "industry": industry_match,
                "experience": experience,
                "business_stage": stage,
                "geography": geography,
            },
        })
    if not candidates:
        return [], options

    # Greedy, soft diversity: a different format or facet can win when signals are close.
    duplicate_ids = {}
    for row in candidates:
        signature = row["text_signature"]
        if signature is not None:
            duplicate_ids.setdefault(signature, []).append(row["item"]["entity_key"])
    selected_rows, kind_counts, seen_signatures = [], Counter(), set()
    while candidates and len(selected_rows) < limit:
        def key(row):
            item = row["item"]
            overlaps = [
                len(row["facets"] & old["facets"]) / len(row["facets"] | old["facets"])
                for old in selected_rows if row["facets"] | old["facets"]
            ]
            adjusted = row["preference"] - 0.15 * kind_counts[item["kind"]] - 0.10 * max(overlaps, default=0)
            region_deferred = row["evidence"]["geography"]["status"] in {
                "possible_region_unknown", "possible_other_region",
            }
            # Identifier is only the final tie-break for otherwise indistinguishable fields.
            return (region_deferred, -row["title_match"], -row["description_match"], -adjusted, *row["stable_order"])

        candidates.sort(key=key)
        chosen = candidates.pop(0)
        signature = chosen["verified_signature"]
        if signature is not None and signature in seen_signatures:
            continue
        possible_duplicates = sorted(
            key for key in duplicate_ids.get(chosen["text_signature"], [])
            if key != chosen["item"]["entity_key"]
        )
        if signature is not None:
            seen_signatures.add(signature)
        chosen["evidence"]["possible_duplicate_entity_keys"] = possible_duplicates
        selected_rows.append(chosen)
        kind_counts[chosen["item"]["kind"]] += 1

    keys = ("entity_key", "kind", "title", "description", "topics", "tags", "industries",
            "access_type", "canonical_url", "data_quality_flags")
    results = []
    for row in selected_rows:
        item = row["item"]
        results.append({
            **{key: item.get(key) for key in keys},
            "promotion": promotion_for(item),
            "price": price_fact(item),
            "reason": "Материал отмечен в выбранном направлении: " + ", ".join(row["evidence"]["matched_facets"]),
            "method": "cold_start_facets_v1",
            "profile_evidence": row["evidence"],
        })
    return results, options
