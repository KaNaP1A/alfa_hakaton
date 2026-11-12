"""End-to-end ranking audit and validation-only BM25 search. Never installs a model.

The cached signals use the production implementation; gates, rules, exact-title
priority and explanations are still executed by SearchEngine.search on every trial.
"""

import argparse
import itertools
import json
import math
import random
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from functools import lru_cache
from pathlib import Path

from alfa_reco.cli import atomic_json, sha256
from alfa_reco.retrieval import BM25Index, RankingConfig
from alfa_reco.search import SearchEngine


def pooled_metrics(order, labels, k=5):
    values = [labels.get(key, 0) for key in order[:k]]
    positive = {key for key, grade in labels.items() if grade >= 2}

    def dcg(grades):
        return sum((2**grade - 1) / math.log2(i + 2) for i, grade in enumerate(grades))

    ideal = dcg(sorted(labels.values(), reverse=True)[:k])
    return {
        "ndcg5_pooled": dcg(values) / ideal if ideal else None,
        "precision5_pooled": sum(v >= 2 for v in values) / k,
        "mrr5_pooled": next((1 / r for r, v in enumerate(values, 1) if v >= 2), 0.0),
        "recall5_judged": len(set(order[:k]) & positive) / len(positive) if positive else None,
        "judged5": sum(key in labels for key in order[:k]) / k,
        "returned5": len(order[:k]),
        "empty": float(not order),
    }


def family_average(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["family"]].append(row["metrics"])
    if not groups:
        raise ValueError("Cannot evaluate an empty split")
    result = {}
    for key in rows[0]["metrics"]:
        means = []
        for group in groups.values():
            values = [r[key] for r in group if r[key] is not None]
            if values:
                means.append(statistics.mean(values))
        result[key] = statistics.mean(means) if means else None
    return {"queries": len(rows), "families": len(groups), **result}


def stability(first, second):
    one, two = set(first), set(second)
    union = one | two
    return {
        "exact_order": first == second,
        "same_set": one == two,
        "jaccard5": len(one & two) / len(union) if union else None,
        "both_empty": not union,
        "both_nonempty": bool(one and two),
        "top1_equal_nonempty": bool(first and second and first[0] == second[0]),
    }


def validate_cases(cases, catalog):
    ids, families, texts = set(), {}, {}
    available = {x["entity_key"] for x in catalog}
    for row in cases:
        if row["id"] in ids or row["split"] not in {"train", "val", "test"}:
            raise ValueError("Duplicate query or invalid split")
        ids.add(row["id"])
        if families.setdefault(row["family"], row["split"]) != row["split"]:
            raise ValueError("Family crosses splits")
        text = " ".join(row["query"].casefold().split())
        if texts.setdefault(text, row["split"]) != row["split"]:
            raise ValueError("Identical query crosses splits")
        keys = [j["entity_key"] for j in row["judgments"]]
        if len(keys) != len(set(keys)) or not set(keys) <= available:
            raise ValueError("Invalid judgment IDs")
        if any(type(j["grade"]) is not int or not 0 <= j["grade"] <= 3 for j in row["judgments"]):
            raise ValueError("Invalid grade")
    if not any(row["split"] == "val" for row in cases):
        raise ValueError("Validation split required")


def cache_signals(engine):
    # Bounded, experiment-local caches; no production request cache is introduced.
    engine.dense_signals = lru_cache(maxsize=2048)(engine.dense_signals)
    original = engine.retriever.signals

    @lru_cache(maxsize=256)
    def cached(query, semantic, k1, b):
        return original(
            query,
            engine.dense_signals(query) if semantic else None,
            config=RankingConfig(bm25_k1=k1, bm25_b=b),
        )

    def signals(query, dense=None, selected_keys=(), config=None):
        config = config or RankingConfig()
        if selected_keys:
            return original(query, dense, selected_keys, config=config)
        return cached(query, dense is not None, config.bm25_k1, config.bm25_b)

    engine.retriever.signals = signals


def evaluate(engine, cases, mode, config=None, details=False):
    rows = []
    for case in cases:
        start = time.perf_counter()
        payload = engine.search(case["query"], mode=mode, ranking_config=config)
        order = [r["entity_key"] for r in payload["results"]]
        labels = {j["entity_key"]: j["grade"] for j in case["judgments"]}
        rows.append(
            {
                "id": case["id"],
                "family": case["family"],
                "query": case["query"],
                "metrics": pooled_metrics(order, labels),
                "top5": [
                    {
                        "key": r["entity_key"],
                        "title": r["title"],
                        "grade": labels.get(r["entity_key"]),
                    }
                    for r in payload["results"]
                ],
                "latency_ms": (time.perf_counter() - start) * 1000,
            }
        )
    summary = family_average(rows)
    return {"summary": summary, **({"rows": rows} if details else {})}


def bootstrap_delta(first, second, seed=42):
    a, b = defaultdict(list), defaultdict(list)
    for row in first:
        if row["metrics"]["ndcg5_pooled"] is not None:
            a[row["family"]].append(row["metrics"]["ndcg5_pooled"])
    for row in second:
        if row["metrics"]["ndcg5_pooled"] is not None:
            b[row["family"]].append(row["metrics"]["ndcg5_pooled"])
    deltas = [statistics.mean(b[k]) - statistics.mean(a[k]) for k in sorted(a.keys() & b.keys())]
    if not deltas:
        return None
    rng = random.Random(seed)
    samples = sorted(statistics.mean(rng.choices(deltas, k=len(deltas))) for _ in range(2000))
    return {
        "families": len(deltas),
        "mean_delta": statistics.mean(deltas),
        "ci95": [samples[49], samples[1949]],
        "resampling": "paired families, 2000 draws",
    }


def calibrate(engine, cases, output):
    validation = [c for c in cases if c["split"] == "val"]
    trials = []
    # Both defaults are included. No test labels are touched in candidate selection.
    combinations = list(
        itertools.product(
            [0.3, 0.8, 1.2, 1.5, 2.0, 3.0], [0.0, 0.25, 0.5, 0.75, 1.0], [1.0, 2.0, 4.0]
        )
    )
    for i, (k1, b, title) in enumerate(combinations):
        config = RankingConfig(bm25_k1=k1, bm25_b=b, title=title)
        metrics = evaluate(engine, validation, "hybrid", config)["summary"]
        trials.append({"parameters": asdict(config), "validation": metrics})
        if (i + 1) % 15 == 0:
            print(f"BM25 grid {i + 1}/{len(combinations)}", flush=True)

    def key(row):
        p = row["parameters"]
        distance = sum(abs(p[k] - asdict(RankingConfig())[k]) for k in p)
        return (-row["validation"]["ndcg5_pooled"], distance, json.dumps(p, sort_keys=True))

    trials.sort(key=key)
    best = RankingConfig(**trials[0]["parameters"])
    secondary = []
    for facet, body, dense in itertools.product(
        [0.0, 0.5, 1.0], [0.0, 0.25, 0.75], [0.5, 1.0, 2.0]
    ):
        config = replace(
            best, topics=facet, tags=facet, industries=facet, body=body, dense_weight=dense
        )
        secondary.append(
            {
                "parameters": asdict(config),
                "validation": evaluate(engine, validation, "hybrid", config)["summary"],
            }
        )
    secondary.sort(key=key)
    best = RankingConfig(**secondary[0]["parameters"])
    comparison = {}
    for split in ("train", "val", "test"):
        subset = [c for c in cases if c["split"] == split]
        base = evaluate(engine, subset, "hybrid", RankingConfig(), True)
        chosen = evaluate(engine, subset, "hybrid", best, True)
        comparison[split] = {
            "baseline": base,
            "selected": chosen,
            "ndcg_delta_bootstrap": bootstrap_delta(base["rows"], chosen["rows"]),
        }
    atomic_json(output / "bm25_trials.json", trials)
    atomic_json(output / "fusion_trials.json", secondary)
    atomic_json(
        output / "selected_config.json",
        {
            "catalog_sha256": engine.manifest["catalog_sha256"],
            "parameters": asdict(best),
            "chosen_on": "validation family-macro pooled NDCG@5 through SearchEngine.search",
            "experimental": True,
            "installed": False,
            "warning": "Provisional assistant labels; previously observed test; no global optimum claim. Retrain CatBoost and recalibrate ensemble before use with changed BM25 features.",
        },
    )
    return {
        "primary_trials": len(trials),
        "secondary_trials": len(secondary),
        "selected": asdict(best),
        "comparison": comparison,
    }


def check_robustness(engine):
    data = json.loads(Path("evaluation/robustness_cases.json").read_text())
    result = {}
    for mode in ("bm25", "hybrid", "catboost", "ensemble"):
        rows = []
        for case in data["pairs"]:
            first, second = [engine.search(q, mode=mode) for q in case["queries"]]
            a, b = [[r["entity_key"] for r in p["results"]] for p in (first, second)]
            rows.append(
                {
                    **case,
                    **stability(a, b),
                    "first_titles": [r["title"] for r in first["results"]],
                    "second_titles": [r["title"] for r in second["results"]],
                }
            )
        summary = {}
        for group in sorted({r["type"] for r in rows}):
            selected = [r for r in rows if r["type"] == group]
            nonempty = [r for r in selected if r["both_nonempty"]]
            summary[group] = {
                "pairs": len(selected),
                "both_empty": sum(r["both_empty"] for r in selected),
                "exact_order": sum(r["exact_order"] for r in selected),
                "same_set": sum(r["same_set"] for r in selected),
                "both_nonempty": len(nonempty),
                "top1_equal_nonempty": sum(r["top1_equal_nonempty"] for r in selected),
                "mean_jaccard_nonempty_union": statistics.mean(
                    r["jaccard5"] for r in selected if r["jaccard5"] is not None
                )
                if any(r["jaccard5"] is not None for r in selected)
                else None,
            }
        result[mode] = {"summary": summary, "rows": rows}
        print(f"Robustness {mode} complete", flush=True)
    return result


def stress_bm25(size=50000):
    rng = random.Random(20261112)
    vocabulary = [f"term{i}" for i in range(500)]
    start = time.perf_counter()
    index = BM25Index([" ".join(rng.choices(vocabulary, k=20 + i % 180)) for i in range(size)])
    build = time.perf_counter() - start
    latencies = []
    for _ in range(100):
        query = " ".join(rng.sample(vocabulary, 5))
        start = time.perf_counter()
        scores = index.score(query)
        latencies.append((time.perf_counter() - start) * 1000)
        if len(scores) != size or not all(math.isfinite(s) and s >= 0 for s in scores):
            raise AssertionError("Non-finite scores or wrong result count")
        if scores != index.score(" ".join(reversed(query.split()))):
            raise AssertionError("Order-dependent lexical scores")
    return {
        "documents": size,
        "queries": 100,
        "build_seconds": build,
        "p50_ms": statistics.median(latencies),
        "p95_ms": sorted(latencies)[94],
        "invariants_passed": True,
        "limitation": "Synthetic lexical corpus, not full HTTP or semantic load testing.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--catalog", default="artifacts/catalog")
    parser.add_argument("--phase", choices=("baseline", "calibrate", "full"), default="full")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    path = Path("evaluation/ensemble_cases_v2.json")
    cases = json.loads(path.read_text())["queries"]
    engine = SearchEngine(args.catalog, semantic=True, llm_enabled=False)
    validate_cases(cases, engine.catalog)
    cache_signals(engine)
    report = {
        "catalog_sha256": engine.manifest["catalog_sha256"],
        "dataset_sha256": sha256(path),
        "vectors_sha256": engine.manifest["semantic"]["vectors_sha256"],
        "split_counts": dict(Counter(c["split"] for c in cases)),
        "source_hashes": {str(p): sha256(p) for p in sorted(Path("src/alfa_reco").glob("*.py"))},
        "limits": "Assistant labels, four judged candidates/query, test already seen in development. Unjudged treated as zero only in explicitly pooled metrics. Empty/empty stability has no Jaccard score. LLM disabled. No online conversion or universal invariance claims.",
    }
    if args.phase in ("baseline", "full"):
        report["quality"] = {}
        for mode in ("bm25", "hybrid", "catboost", "ensemble"):
            report["quality"][mode] = {
                split: evaluate(
                    engine, [c for c in cases if c["split"] == split], mode, details=True
                )
                for split in ("train", "val", "test")
            }
            print(f"Quality {mode} complete", flush=True)
        report["robustness"] = check_robustness(engine)
        report["no_answer"] = {}
        probes = json.loads(Path("evaluation/uncertainty_holdout_2026_11_12.json").read_text())[
            "cases"
        ]
        for mode in ("bm25", "hybrid", "catboost", "ensemble"):
            rows = []
            for case in probes:
                payload = engine.search(case["query"], mode=mode)
                rows.append(
                    {
                        **case,
                        "returned": len(payload["results"]),
                        "titles": [r["title"] for r in payload["results"]],
                    }
                )
            report["no_answer"][mode] = rows
        report["stress"] = stress_bm25()
    if args.phase in ("calibrate", "full"):
        report["calibration"] = calibrate(engine, cases, args.output)
    atomic_json(args.output / "report.json", report)
    print(f"Wrote {args.output / 'report.json'}", flush=True)


if __name__ == "__main__":
    main()
