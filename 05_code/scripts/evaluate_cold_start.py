"""Compare cold-start structure to the legacy category baseline, without relevance labels."""

import argparse
import json
import time
from pathlib import Path

from alfa_reco.cold_start import _text_coverage, category_facets
from alfa_reco.personalization import CATEGORIES, facets
from alfa_reco.profile import recommend_for_profile
from alfa_reco.search import SearchEngine


def summarize(results, labels, strong_labels):
    keys = [item["entity_key"] for item in results]
    matched = [facets(item) & labels for item in results]
    return {
        "results": len(results),
        "unique_entity_keys": len(set(keys)),
        "all_in_selected_category": all(bool(value) for value in matched),
        "without_strong_category_facet": sum(not bool(facets(item) & strong_labels) for item in results),
        "distinct_kinds": len({item["kind"] for item in results}),
        "distinct_matched_facets": len(set().union(*matched)),
        "titles_with_facet_words": sum(
            _text_coverage(selected, item["title"]) > 0
            for item, selected in zip(results, matched, strict=True)
        ),
    }


def evaluate(catalog_dir, output):
    if output.exists():
        raise ValueError("Output already exists")
    engine = SearchEngine(catalog_dir, semantic=False, llm_enabled=False)
    empty = recommend_for_profile(engine, {"generation": engine.generation})
    result = {
        "generation": engine.generation,
        "catalog_sha256": engine.manifest["catalog_sha256"],
        "no_profile": {
            "status": empty["status"],
            "results": len(empty["results"]),
            "offered_directions": len(empty["onboarding"]["options"]),
        },
        "categories": {},
        "limitations": "Five synthetic profiles only; these structural counts and local times do not measure relevance, user satisfaction or conversion. Counts reflect the offline snapshot, not current access rights.",
    }
    for name, (_, labels) in CATEGORIES.items():
        # The former category-only path gave every matching material score 1 and
        # used entity_key as the tie-break. Reproduce it without the new code path.
        baseline = sorted(
            (item for item in engine.catalog if item["kind"] != "glossary" and facets(item) & labels),
            key=lambda item: item["entity_key"],
        )[:5]
        start = time.perf_counter()
        cold = recommend_for_profile(engine, {"generation": engine.generation, "categories": [name]}, limit=5)
        elapsed = (time.perf_counter() - start) * 1000
        result["categories"][name] = {
            "legacy": summarize(baseline, labels, category_facets(name)),
            "cold_start": summarize(cold["results"], labels, category_facets(name)),
            "status": cold["status"],
            "cold_start_ms_single_local_run": round(elapsed, 2),
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("artifacts/catalog"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.catalog, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
