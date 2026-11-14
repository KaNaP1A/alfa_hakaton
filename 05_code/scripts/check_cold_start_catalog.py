"""Exercise every available cold-start category/facet; this is not a relevance evaluation."""

import argparse
import json
from collections import Counter
from pathlib import Path

from alfa_reco.cold_start import starter_options
from alfa_reco.eligibility import USER_KINDS
from alfa_reco.geography import geographic_hint
from alfa_reco.personalization import CATEGORIES, facets
from alfa_reco.profile import recommend_for_profile
from alfa_reco.search import SearchEngine


def check(catalog_dir):
    engine = SearchEngine(catalog_dir, semantic=False, llm_enabled=False)
    catalog_by_key = {item["entity_key"]: item for item in engine.catalog}
    geography = Counter(geographic_hint(item["title"])["status"] for item in engine.catalog
                        if item["kind"] in USER_KINDS)
    categories_checked, facets_checked, outputs = 0, 0, 0
    empty = recommend_for_profile(engine, {"generation": engine.generation})
    if empty["results"]:
        raise AssertionError("Empty profile produced unsupported results")
    for category in CATEGORIES:
        options = starter_options(engine.catalog, [category])["options"]
        if not options:
            continue
        categories_checked += 1
        for option in options:
            focus = option["focus_facet"]
            profile = {"generation": engine.generation, "categories": [category], "focus_facet": focus}
            result = recommend_for_profile(engine, profile, limit=5)
            facets_checked += 1
            if not result["results"]:
                raise AssertionError(f"Offered facet produced no result: {category}/{focus}")
            keys = [item["entity_key"] for item in result["results"]]
            if len(keys) != len(set(keys)):
                raise AssertionError("Repeated identifier in a result")
            if not all(focus in facets(catalog_by_key[key]) for key in keys):
                raise AssertionError("Result lacks the explicitly selected facet")
            outputs += len(keys)
    return {
        "generation": engine.generation,
        "category_profiles_checked": categories_checked,
        "category_facet_profiles_checked": facets_checked,
        "total_facet_results_checked": outputs,
        "geographic_title_hint_counts": dict(geography),
        "limitations": "Structural checks only; geographic hints are unverified and cannot measure false positives or misses. No relevance, personalization, or current access claims.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("artifacts/catalog"))
    args = parser.parse_args()
    print(json.dumps(check(args.catalog), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
