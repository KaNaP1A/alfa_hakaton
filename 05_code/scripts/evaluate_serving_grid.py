"""Evaluate all fusion weights with cached serving rules and verify against SearchEngine."""

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from audit_ranking import family_average, pooled_metrics
from compare_score_fusions import grid, normalize, readlines

from alfa_reco.bundle import atomic_json
from alfa_reco.eligibility import USER_KINDS
from alfa_reco.query_rules import exclusion_multiplier, intent_multiplier, plan_query
from alfa_reco.search import SearchEngine
from alfa_reco.text import tokens


def main():
    root = Path("artifacts/annotation_pool/relevance_v1")
    cases = readlines(root / "pool.jsonl")
    grades = {
        (r["query_id"], r["entity_key"]): r["grade"]
        for r in readlines(root / "automatic_qwen/ratings.jsonl")
    }
    weights = grid()
    engine = SearchEngine("artifacts/catalog", semantic=True)
    backend = engine.relevance_backend()
    old_prepare, old_score = backend.prepare, backend.score
    allowed = {i for i, item in enumerate(engine.catalog) if item["kind"] in USER_KINDS}
    groups, common = defaultdict(list), defaultdict(list)
    coverage = defaultdict(lambda: {"queries": 0, "results": 0, "unknown_results": 0})
    checked = 0
    chosen = json.loads(Path("artifacts/fusion_comparison_v2/report.json").read_text())["selected"]
    checkweights = {
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
        tuple(chosen[k] for k in ["bm25", "minilm", "e5", "catboost"]),
    }
    for number, case in enumerate(cases, 1):
        query = case["query"]
        prep = old_prepare(query)
        ids = prep["candidates"]
        plan = plan_query(query)
        mini = engine.dense_signals(query)
        minisim = np.max(np.array([mini[k] for k in ("card", "body", "lesson")]), axis=0)
        cols = [
            np.asarray(prep["lexical"])[ids],
            minisim[ids],
            np.asarray(prep["e5"]["card"])[ids],
            backend.model.predict(prep["features"][ids]),
        ]
        signals = np.stack([normalize(c) for c in cols], axis=1)
        positive = tokens(plan.positive_query)
        priority = sorted(
            [
                i
                for i in allowed
                if positive and positive == tokens(engine.catalog[i]["title"].rstrip(" ,.;!?"))
            ],
            key=lambda i: engine.catalog[i]["entity_key"],
        )
        candidates = set(ids) | set(priority)
        multipliers = {
            i: exclusion_multiplier(engine.retriever.title_terms[i], plan.excluded_terms)
            * intent_multiplier(engine.catalog[i]["title"], plan)
            for i in candidates
        }
        admitted = {
            i: backend.support(prep, i, conflict=multipliers[i] < 1)["admitted"] for i in candidates
        }
        use_rules = bool(plan.excluded_terms or plan.retention_expansion or plan.debt_expansion)

        def fast(
            ranked,
            *,
            apply_rules=use_rules,
            multipliers=multipliers,
            priority=priority,
            admitted=admitted,
        ):
            if apply_rules:
                prior = {i: r + 1 for r, i in enumerate(ranked)}
                ranked = sorted(
                    ranked,
                    key=lambda i: (
                        -multipliers[i] / (engine.ranking_config.rrf_k + prior[i]),
                        engine.catalog[i]["entity_key"],
                    ),
                )
            first = list(dict.fromkeys(priority + ranked))[:60]
            return [engine.catalog[i]["entity_key"] for i in first if admitted[i]][:5]

        def cached(
            q,
            allowed=None,
            selected_keys=(),
            vector=None,
            *,
            expected=query,
            value=prep,
            allowed_set=allowed,
        ):
            if (
                q == expected
                and (allowed is None or allowed == allowed_set)
                and not selected_keys
                and vector is None
            ):
                return value
            return old_prepare(q, allowed, selected_keys, vector)

        backend.prepare = cached
        backend.score = old_score
        baseline = [r["entity_key"] for r in engine.search(query, mode="relevance")["results"]]
        baseline_order, _ = old_score(prep)
        if fast(baseline_order) != baseline:
            raise AssertionError("Cached rules differ from baseline serving")
        checked += 1
        keys = {c["entity_key"] for c in case["candidates"] if c["kind"] != "glossary"}
        labels = {k: grades.get((case["query_id"], k)) for k in keys}
        if not keys or any(type(v) is not int for v in labels.values()):
            raise ValueError("Incomplete labels")
        results = []
        for i, w in enumerate(weights):
            vals = signals @ np.asarray(w)
            scores = {k: float(v) for k, v in zip(ids, vals, strict=True)}
            ranked = sorted(ids, key=lambda k: (-scores[k], engine.catalog[k]["entity_key"]))
            output = fast(ranked)
            results.append(output)
            if w in checkweights:

                def score(_, *, ranked=ranked, values=scores):
                    return ranked, values

                backend.score = score
                actual = [
                    r["entity_key"] for r in engine.search(query, mode="relevance")["results"]
                ]
                if output != actual:
                    raise AssertionError(
                        f"Cached rules differ from serving: {case['query_id']}, {w}"
                    )
                checked += 1
            counts = coverage[i, case["split"]]
            counts["queries"] += 1
            counts["results"] += len(output)
            counts["unknown_results"] += len(set(output) - keys)
            if set(output) <= keys:
                groups[i, case["split"]].append(
                    {"family": case["family"], "metrics": pooled_metrics(output, labels)}
                )
        all_judged = set(baseline) <= keys and all(set(output) <= keys for output in results)
        if all_judged:
            for i, output in enumerate(results):
                common[i, case["split"]].append(
                    {"family": case["family"], "metrics": pooled_metrics(output, labels)}
                )
            common["current", case["split"]].append(
                {"family": case["family"], "metrics": pooled_metrics(baseline, labels)}
            )
        backend.score = old_score
        if number % 5 == 0:
            print("Verified serving grid", number, "/", len(cases), "checks", checked, flush=True)
    report = {
        "configurations": len(weights),
        "grid_step": 0.1,
        "serving_equivalence_checks": checked,
        "trials": [],
        "current_common": {},
        "limits": "All 286 weights use cached production candidate sets, exact-title priority, query rules and admission gates. Cached output is asserted equal to real SearchEngine.search for the baseline and five representative configurations per query. Real labels are automatic; queries previously seen, no independent human holdout. Unknown results are excluded, never assigned zero. Common subset can be small and biased. No synthetic test or installation.",
    }
    for i, w in enumerate(weights):
        report["trials"].append(
            {
                "weights": dict(zip(["bm25", "minilm", "e5", "catboost"], w, strict=True)),
                "per_variant": {
                    s: family_average(groups[i, s])
                    for s in ["train", "validation", "test"]
                    if groups[i, s]
                },
                "common_all": {
                    s: family_average(common[i, s])
                    for s in ["train", "validation", "test"]
                    if common[i, s]
                },
                "coverage": {s: coverage[i, s] for s in ["train", "validation", "test"]},
            }
        )
    report["current_common"] = {
        s: family_average(common["current", s])
        for s in ["train", "validation", "test"]
        if common["current", s]
    }
    atomic_json(Path("artifacts/fusion_comparison_v2/full_serving_grid.json"), report)
    print(
        json.dumps(
            {
                "configurations": len(weights),
                "serving_equivalence_checks": checked,
                "current_common": report["current_common"],
                "limits": report["limits"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
