"""Catalog-grounded interest directory; counts do not represent user access."""

import json
from collections import defaultdict
from pathlib import Path

from .cold_start import category_facets
from .eligibility import USER_KINDS
from .personalization import CATEGORIES

CONFIG_PATH = Path(__file__).with_name("interest_facets.json")
MAX_FACET_LENGTH = 150


def normalize_facet(value):
    if not isinstance(value, str):
        raise ValueError("Interest facet must be a string")
    return " ".join(value.split())


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate key in interest configuration")
        result[key] = value
    return result


def load_interest_config(path=CONFIG_PATH):
    """Validate versioned additions; these do not affect existing recommendations."""
    try:
        with Path(path).open(encoding="utf-8") as stream:
            config = json.load(stream, object_pairs_hook=_unique_object)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Invalid interest configuration") from error
    if (not isinstance(config, dict) or set(config) != {"version", "categories"}
            or type(config["version"]) is not int or config["version"] != 1
            or not isinstance(config["categories"], dict)):
        raise ValueError("Invalid interest configuration schema or version")
    additions = {}
    for category, values in config["categories"].items():
        if category not in CATEGORIES or not isinstance(values, list):
            raise ValueError("Invalid interest category or facets")
        seen = {normalize_facet(v).casefold() for v in category_facets(category)}
        if category == "finance":
            seen.add("законы")
        additions[category] = []
        for value in values:
            value = normalize_facet(value)
            key = value.casefold()
            if not value or len(value) > MAX_FACET_LENGTH or key in seen:
                raise ValueError("Invalid or duplicate interest facet")
            seen.add(key)
            additions[category].append(value)
    return additions


def interest_directory(catalog, generation, *, config_path=CONFIG_PATH):
    """Return unique catalog snapshot counts per category and normalized topic/tag."""
    additions = load_interest_config(config_path)
    facts = defaultdict(lambda: {"labels": set(), "sources": set(), "keys": set()})
    for item in catalog:
        if item.get("kind") not in USER_KINDS:
            continue
        key = item.get("entity_key")
        if not isinstance(key, str) or not key:
            raise ValueError("Catalog material must have an entity_key")
        for field in ("topics", "tags"):
            for raw in item.get(field) or []:
                label = normalize_facet(raw)
                if not label:
                    continue
                fact = facts[label.casefold()]
                fact["labels"].add(label)
                fact["sources"].add(field)
                fact["keys"].add(key)

    categories = []
    for category, (label, _) in CATEGORIES.items():
        allowed = {normalize_facet(v).casefold() for v in category_facets(category)}
        allowed.update(normalize_facet(v).casefold() for v in additions.get(category, []))
        topics = []
        material_keys = set()
        for facet in allowed & facts.keys():
            fact = facts[facet]
            title = min(fact["labels"], key=lambda value: (value.casefold(), value))
            material_keys.update(fact["keys"])
            topics.append({
                "value": title,
                "label": title,
                "sources": [field for field in ("topics", "tags") if field in fact["sources"]],
                "material_count": len(fact["keys"]),
            })
        if topics:
            topics.sort(key=lambda value: (-value["material_count"], value["label"].casefold(), value["label"]))
            categories.append({"id": category, "label": label, "material_count": len(material_keys), "topics": topics})
    return {"generation": generation, "categories": categories}
