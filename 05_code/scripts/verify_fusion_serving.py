"""End-to-end diagnostic of the validation-selected fusion against the existing profile."""

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from audit_ranking import family_average, pooled_metrics
from compare_score_fusions import normalize, readlines

from alfa_reco.bundle import atomic_json
from alfa_reco.eligibility import USER_KINDS
from alfa_reco.search import SearchEngine


def main():
    root = Path("artifacts/annotation_pool/relevance_v1")
    cases = readlines(root / "pool.jsonl")
    labels = {
        (r["query_id"], r["entity_key"]): r["grade"]
        for r in readlines(root / "automatic_qwen/ratings.jsonl")
    }
    config = json.loads(Path("artifacts/fusion_comparison_v2/report.json").read_text())
    weights = np.array([config["selected"][n] for n in ["bm25", "minilm", "e5", "catboost"]])
    engine = SearchEngine("artifacts/catalog", semantic=True)
    allowed_all = {i for i, item in enumerate(engine.catalog) if item["kind"] in USER_KINDS}
    backend = engine.relevance_backend()
    original_prepare, original_score = backend.prepare, backend.score
    complete = defaultdict(list)
    counts = defaultdict(
        lambda: {"queries": 0, "comparable": 0, "unjudged_results": 0, "returned": 0}
    )
    details = []
    for n, case in enumerate(cases, 1):
        query = case["query"]
        prep = original_prepare(query)
        mini = engine.dense_signals(query)
        indices = prep["candidates"]
        features = prep["features"][indices]
        cat = backend.model.predict(features)
        minival = np.max(np.array([mini[k] for k in ("card", "body", "lesson")]), axis=0)
        columns = [
            np.asarray(prep["lexical"])[indices],
            minival[indices],
            np.asarray(prep["e5"]["card"])[indices],
            cat,
        ]
        vals = np.stack([normalize(c) for c in columns], axis=1) @ weights
        scores = {i: float(v) for i, v in zip(indices, vals, strict=True)}
        order = sorted(indices, key=lambda i: (-scores[i], engine.catalog[i]["entity_key"]))

        def cached_prepare(
            q, allowed=None, selected_keys=(), vector=None, *, expected=query, value=prep
        ):
            if (
                q == expected
                and (allowed is None or allowed == allowed_all)
                and not selected_keys
                and vector is None
            ):
                return value
            return original_prepare(q, allowed, selected_keys, vector)

        backend.prepare = cached_prepare
        backend.score = original_score
        baseline = engine.search(query, mode="relevance")["results"]

        def weighted_score(prepared, *, ranked=order, values=scores):
            return ranked, values

        backend.score = weighted_score
        candidate = engine.search(query, mode="relevance")["results"]
        backend.score = original_score
        keys = {c["entity_key"] for c in case["candidates"] if c["kind"] != "glossary"}
        grades = {k: labels.get((case["query_id"], k)) for k in keys}
        orders = {
            "current": [r["entity_key"] for r in baseline],
            "selected_fusion": [r["entity_key"] for r in candidate],
        }
        count = counts[case["split"]]
        count["queries"] += 1
        count["returned"] += sum(map(len, orders.values()))
        count["unjudged_results"] += sum(len(set(v) - keys) for v in orders.values())
        known = (
            bool(keys)
            and all(type(v) is int for v in grades.values())
            and all(set(v) <= keys for v in orders.values())
        )
        if known:
            count["comparable"] += 1
            for method, v in orders.items():
                complete[case["split"], method].append(
                    {"family": case["family"], "metrics": pooled_metrics(v, grades)}
                )
        details.append(
            {
                "query_id": case["query_id"],
                "split": case["split"],
                "all_returned_judged": known,
                "orders": orders,
            }
        )
        if n % 25 == 0:
            print("End-to-end", n, "/", len(cases), flush=True)
    summary = {}
    for (split, method), rows in complete.items():
        summary.setdefault(split, {})[method] = family_average(rows)
    out = {
        "weights": config["selected"],
        "counts": dict(counts),
        "metrics_on_common_fully_judged_queries": summary,
        "details": details,
        "limits": "End-to-end includes existing candidate generation, exact-title priority, admission rules and alternatives; the fusion is experimental and min-max normalized within retrieved candidates. Only real queries where every returned item from BOTH methods is in the existing automatically judged pool contribute to metrics. Others are excluded, never assigned zero. This subset can be biased. Prior validation and test are small and already observed; no human labels, no independent holdout, no model installation.",
    }
    atomic_json(Path("artifacts/fusion_comparison_v2/serving_report.json"), out)
    print(
        json.dumps({k: v for k, v in out.items() if k != "details"}, ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
