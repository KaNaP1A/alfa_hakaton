"""Post-selection ablations and blinded pool refresh. Never selects or installs a model."""

import argparse
import hashlib
import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from audit_ranking import family_average
from build_annotation_pool import jsonl, review_markdown
from train_relevance import evaluate

from alfa_reco.bundle import atomic_json, sha256
from alfa_reco.search import SearchEngine


def slices(engine, cases, rows):
    by_id = {r["entity_key"]: r for r in engine.catalog}
    queries = {q["id"]: q for q in cases}
    groups = defaultdict(list)
    for row in rows:
        case = queries[row["id"]]
        best = max(j["grade"] for j in case["judgments"])
        targets = [by_id[j["entity_key"]] for j in case["judgments"] if j["grade"] == best]
        for kind in sorted({i["kind"] for i in targets}):
            groups["material_kind:" + kind].append(row)
        for topic in sorted({t for i in targets for t in i.get("topics", [])}):
            groups["positive_catalog_topic:" + topic].append(row)
        length = len(case["query"].split())
        groups[
            "query_length:" + ("short" if length <= 4 else "medium" if length <= 10 else "long")
        ].append(row)
    return {name: family_average(values) for name, values in sorted(groups.items())}


def expanded_pool(engine, source, output):
    if output.exists():
        raise ValueError("Annotation output must be new")
    original = [
        json.loads(line) for line in (source / "pool.jsonl").read_text().splitlines() if line
    ]
    old_rankings = {
        r["query_id"]: r
        for r in [
            json.loads(line)
            for line in (source / "rankings.jsonl").read_text().splitlines()
            if line
        ]
    }
    pool, rankings, judgments = [], [], []
    for number, row in enumerate(original, 1):
        result = engine.search(row["query"], mode="relevance")
        candidates = {c["entity_key"]: c for c in row["candidates"]}
        for item in result["results"]:
            candidates[item["entity_key"]] = {
                key: item[key] for key in ("entity_key", "title", "description", "kind")
            }
        ordered = sorted(
            candidates.values(),
            key=lambda r: hashlib.sha256(
                ("relevance-pool:" + row["query_id"] + r["entity_key"]).encode()
            ).hexdigest(),
        )
        pool.append({**row, "candidates": ordered})
        rankings.append(
            {
                "query_id": row["query_id"],
                "rankings": {
                    **{
                        "historical_" + method: order
                        for method, order in old_rankings[row["query_id"]]["rankings"].items()
                    },
                    "relevance": [i["entity_key"] for i in result["results"]],
                },
            }
        )
        for item in ordered:
            judgments.append(
                {
                    "query_id": row["query_id"],
                    "entity_key": item["entity_key"],
                    "reviewer_a": None,
                    "reviewer_b": None,
                    "adjudicated": None,
                }
            )
        if number % 25 == 0:
            print("Prepared human pool", number, "/", len(original), flush=True)
    output.mkdir(parents=True)
    hashes = {}
    for name, values in [
        ("pool.jsonl", pool),
        ("rankings.jsonl", rankings),
        ("judgments.jsonl", judgments),
    ]:
        (output / name).write_text(jsonl(values), encoding="utf-8")
        hashes[name] = sha256(output / name)
    (output / "review.md").write_text(review_markdown(pool), encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "catalog_sha256": engine.manifest["catalog_sha256"],
        "parent_pool_sha256": sha256(source / "pool.jsonl"),
        "relevance_manifest_sha256": sha256(engine.relevance_backend().path / "manifest.json"),
        "queries": len(pool),
        "candidates": len(judgments),
        "hashes_before_review": hashes,
        "note": "No labels generated. Previous assistant-authored pool extended with frozen ML top-5. Historical baselines retain their creation snapshot; this is not a fresh blind test. Reviewers must not view rankings.jsonl.",
    }
    atomic_json(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="artifacts/catalog")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--annotation-source", type=Path, default=Path("artifacts/annotation_pool/complex_v3")
    )
    parser.add_argument("--annotation-output", type=Path)
    args = parser.parse_args()
    engine = SearchEngine(args.catalog, semantic=False, llm_enabled=False)
    backend = engine.relevance_backend()
    original = backend.prepare

    @lru_cache(maxsize=200)
    def prepared(query, canonical):
        return original(query)

    def prepare(query, allowed=None, selected_keys=(), vector=None):
        if selected_keys or vector is not None:
            return original(query, allowed, selected_keys, vector)
        return prepared(query, backend.canonical)

    backend.prepare = prepare
    cases = json.loads(Path("evaluation/ensemble_cases_v2.json").read_text())["queries"]
    model = backend.model
    results = {}
    for method, canonical, ranker in [
        ("trained_relevance", True, model),
        ("e5_canonical_without_ranker", True, None),
        ("e5_surface_without_ranker", False, None),
    ]:
        backend.canonical, backend.model = canonical, ranker
        results[method] = {
            split: evaluate(engine, [q for q in cases if q["split"] == split])
            for split in ("val", "test")
        }
        print(
            method,
            {s: r["summary"]["ndcg5_pooled"] for s, r in results[method].items()},
            flush=True,
        )
    backend.canonical, backend.model = True, model
    importance = model.get_feature_importance(type="PredictionValuesChange")
    report = {
        "catalog_sha256": engine.manifest["catalog_sha256"],
        "ablation": results,
        "test_slices": slices(engine, cases, results["trained_relevance"]["test"]["rows"]),
        "feature_importance_prediction_values_change": sorted(
            [
                {"name": name, "importance": float(value)}
                for name, value in zip(model.feature_names_, importance, strict=True)
            ],
            key=lambda r: -r["importance"],
        ),
        "limits": "Post-selection descriptive ablation only, not another model selection. Same calibrated policy for all variants. Assistant labels and previously seen test. Feature importance is not causal. Topic slices use metadata of highest-graded judged items and can overlap.",
    }
    if args.annotation_output:
        report["annotation_pool"] = expanded_pool(
            engine, args.annotation_source, args.annotation_output
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, report)


if __name__ == "__main__":
    main()
