"""Evaluate 3 ranking components and fit weighted RRF on provisional query families."""

import argparse
import itertools
import json
import math
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

import numpy as np

from alfa_reco.cli import atomic_json, load_bundle, sha256
from alfa_reco.eligibility import USER_KINDS
from alfa_reco.ensemble import METHODS, RRF_K, fuse
from alfa_reco.query_interpreter import MODEL, OllamaInterpreter, grounded_match
from alfa_reco.query_rules import plan_query
from alfa_reco.search import SearchEngine
from alfa_reco.storage import output_lock
from alfa_reco.text import embedding_query


def metrics(order, labels):
    relevance = [labels.get(key, 0) for key in order[:5]]
    judged = sum(key in labels for key in order[:5]) / 5
    precision = sum(grade >= 2 for grade in relevance) / 5
    reciprocal = next(
        (1 / rank for rank, key in enumerate(order[:60], 1) if labels.get(key, 0) >= 2), 0.0
    )

    def dcg(grades):
        return sum((2**grade - 1) / math.log2(i + 2) for i, grade in enumerate(grades))

    ideal = dcg(sorted(labels.values(), reverse=True)[:5])
    return {
        "precision5_pooled": precision,
        "mrr60_pooled": reciprocal,
        "ndcg5_pooled": dcg(relevance) / ideal if ideal else 0.0,
        "judged5": judged,
    }


def average(rows):
    return {name: round(sum(row[name] for row in rows) / len(rows), 6) for name in rows[0]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/catalog")
    parser.add_argument("--cases", default="evaluation/ensemble_cases_v2.json")
    parser.add_argument("--results", default="evaluation/ensemble_results_v2")
    parser.add_argument(
        "--with-ollama",
        action="store_true",
        help="Evaluate local Gemma extraction and ranking effect",
    )
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    cases_path = Path(args.cases)
    dataset = json.loads(cases_path.read_text())
    cases = dataset["queries"]
    if len(cases) < 100:
        raise ValueError("At least 100 test cases required")
    families = {}
    seen_ids = set()
    for case in cases:
        if (
            case["id"] in seen_ids
            or families.setdefault(case["family"], case["split"]) != case["split"]
        ):
            raise ValueError("Duplicate query id or family split leakage")
        seen_ids.add(case["id"])
    engine = SearchEngine(args.output, semantic=True)
    config = engine.ranking_config
    allowed = {i for i, item in enumerate(engine.catalog) if item["kind"] in USER_KINDS}
    indexes = {row["entity_key"]: i for i, row in enumerate(engine.catalog)}
    for case in cases:
        judgments = case["judgments"]
        keys = [j["entity_key"] for j in judgments]
        if (
            len(keys) != len(set(keys))
            or any(k not in indexes for k in keys)
            or any(j["grade"] not in (0, 1, 2, 3) for j in judgments)
        ):
            raise ValueError("Invalid or missing judgment")
    qvec = engine.encoder.encode(
        [embedding_query(plan_query(q["query"]).retrieval_query) for q in cases],
        normalize_embeddings=True,
        batch_size=32,
        show_progress_bar=False,
    )
    similarities = engine.vectors @ qvec.T
    prepared = []
    interpreter = OllamaInterpreter(timeout=8) if args.with_ollama else None
    llm_digest = interpreter.model_digest() if interpreter else None
    if args.with_ollama and not llm_digest:
        raise ValueError(
            "Ollama or gemma3:1b is not available; run without --with-ollama for a baseline"
        )
    for col, case in enumerate(cases):
        dense = {
            s: np.zeros(len(engine.catalog), dtype=np.float32) for s in ("card", "body", "lesson")
        }
        for source, mask in engine.unit_masks.items():
            np.maximum.at(dense[source], engine.unit_indices[mask], similarities[mask, col])
        signals = engine.retriever.signals(
            plan_query(case["query"]).retrieval_query,
            {key: value.tolist() for key, value in dense.items()},
            config=config,
        )
        lists, *_ = engine.component_rankings(case["query"], signals, allowed, config)
        named = {
            name: [engine.catalog[i]["entity_key"] for i in ranking]
            for name, ranking in lists.items()
        }
        started = time.monotonic()
        extraction = interpreter.analyze(case["query"]) if interpreter else {"status": "disabled"}
        extraction_elapsed = round((time.monotonic() - started) * 1000, 2)
        candidate_ids = set().union(*named.values())
        match = {
            key: grounded_match(extraction, engine.retriever.context_terms[indexes[key]])
            for key in candidate_ids
        }
        prepared.append((case, named, extraction, match, extraction_elapsed))
        if (col + 1) % 20 == 0:
            print("Evaluated components:", col + 1, "/", len(cases), flush=True)

    def order_fused(lists, weights, match, boost=0.0):
        scores, _ = fuse(lists, weights)
        for item in scores:
            scores[item] *= 1 + boost * match.get(item, 0.0)
        return sorted(scores, key=lambda item: (-scores[item], item))

    def evaluate(split, method=None, weights=None, details=False, llm_boost=0.0):
        rows = []
        for case, lists, extraction, match, elapsed in prepared:
            if case["split"] != split:
                continue
            order = lists[method] if method else order_fused(lists, weights, match, llm_boost)
            labels = {j["entity_key"]: j["grade"] for j in case["judgments"]}
            scored = metrics(order, labels)
            rows.append(
                {
                    "id": case["id"],
                    "family": case["family"],
                    "query": case["query"],
                    "metrics": scored,
                    "extraction": extraction,
                    "extraction_elapsed_ms": elapsed,
                    "top5": [
                        {"entity_key": key, "grade": labels.get(key), "judged": key in labels}
                        for key in order[:5]
                    ],
                }
            )
        if not rows:
            raise ValueError("Empty split")
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["family"]].append(row["metrics"])
        return {
            "summary": average([average(values) for values in grouped.values()]),
            "family_count": len(grouped),
            "queries": rows if details else len(rows),
        }

    individual = {
        method: {
            split: evaluate(split, method=method, details=True)
            for split in ("train", "val", "test")
        }
        for method in METHODS
    }
    raw = {method: individual[method]["val"]["summary"]["ndcg5_pooled"] for method in METHODS}
    denom = sum(raw.values())
    initial = (
        {method: raw[method] / denom for method in METHODS}
        if denom
        else dict.fromkeys(METHODS, 1 / len(METHODS))
    )
    initial_val = evaluate("val", weights=initial)
    # Grid granularity 0.1, minimum 0.1 for each of three components, total 1.
    trials = []
    for parts in itertools.product(range(1, 9), repeat=3):
        if sum(parts) != 10:
            continue
        weights = {name: value / 10 for name, value in zip(METHODS, parts, strict=True)}
        summary = evaluate("val", weights=weights)["summary"]
        trials.append({"weights": weights, "validation": summary})
    trials.sort(
        key=lambda trial: (
            -trial["validation"]["ndcg5_pooled"],
            -trial["validation"]["mrr60_pooled"],
            -trial["validation"]["precision5_pooled"],
            sum((w - 1 / len(METHODS)) ** 2 for w in trial["weights"].values()),
            tuple(trial["weights"][m] for m in METHODS),
        )
    )
    selected = trials[0]["weights"]
    # Tune extraction boost only on validation, with a conservative preference for zero on ties.
    llm_trials = []
    valid_extractions = sum(
        1
        for case, _, extraction, match, _ in prepared
        if case["split"] == "val" and extraction.get("status") == "ok" and any(match.values())
    )
    for boost in (0.0, 0.05, 0.1, 0.2):
        llm_trials.append(
            {
                "boost": boost,
                "validation": evaluate("val", weights=selected, llm_boost=boost)["summary"],
            }
        )
    llm_trials.sort(key=lambda row: (-row["validation"]["ndcg5_pooled"], row["boost"]))
    selected_boost = llm_trials[0]["boost"] if interpreter and valid_extractions >= 5 else 0.0
    report = {
        "schema_version": 1,
        "cases": len(cases),
        "families": len(families),
        "split_cases": {
            split: sum(x["split"] == split for x in cases) for split in ("train", "val", "test")
        },
        "method_metrics": individual,
        "initial_weights_from_validation_ndcg": initial,
        "initial_validation": initial_val,
        "grid_trials": len(trials),
        "selected_weights": selected,
        "selected_train": evaluate(
            "train", weights=selected, details=True, llm_boost=selected_boost
        ),
        "selected_validation": evaluate(
            "val", weights=selected, details=True, llm_boost=selected_boost
        ),
        "selected_test": evaluate("test", weights=selected, details=True, llm_boost=selected_boost),
        "llm_off_test": evaluate("test", weights=selected),
        "llm_evaluation": {
            "enabled": bool(interpreter),
            "model": MODEL if interpreter else None,
            "digest": llm_digest,
            "selected_boost": selected_boost,
            "eligible_validation_cases": valid_extractions,
            "validation_trials": llm_trials,
            "statuses": dict(Counter(extraction["status"] for _, _, extraction, _, _ in prepared)),
            "note": "No ground-truth extraction labels in this experiment; negated queries do not get boost.",
        },
        "warning": "Provisional assistant labels, four judgments/query; unjudged treated as 0. Test previously observed, some new target cards may have been in CatBoost synthetic training. Scores are not unbiased and cannot establish superiority.",
    }
    out = Path(args.results)
    out.mkdir(parents=True, exist_ok=True)
    atomic_json(out / "report.json", report)
    atomic_json(out / "weight_trials.json", trials)
    config = {
        "schema_version": 1,
        "weights": selected,
        "rrf_k": RRF_K,
        "top_per_method": 60,
        "catalog_sha256": engine.manifest["catalog_sha256"],
        "vectors_sha256": engine.manifest["semantic"]["vectors_sha256"],
        "model_sha256": sha256(engine.path / "catboost_small.cbm"),
        "dataset_sha256": sha256(cases_path),
        "method": "validation_grid_0.1_min_0.1_pooled_ndcg5",
        "retrieval_parameters": asdict(config),
        "llm_model": MODEL,
        "llm_digest": llm_digest,
        "llm_boost": selected_boost,
        "warning": report["warning"],
    }
    atomic_json(out / "selected_config.json", config)
    if args.install:
        with output_lock(args.output):
            active, manifest, _ = load_bundle(args.output)
            if (
                active != engine.path
                or manifest["catalog_sha256"] != config["catalog_sha256"]
                or manifest["semantic"]["vectors_sha256"] != config["vectors_sha256"]
            ):
                raise ValueError("Catalog or embeddings changed during experiment")
            if sha256(active / "catboost_small.cbm") != config["model_sha256"]:
                raise ValueError("Model changed during experiment")
            atomic_json(active / "ensemble_config.json", config)
    print(
        json.dumps(
            {
                "cases": len(cases),
                "families": len(families),
                "weights": selected,
                "validation": report["selected_validation"]["summary"],
                "test": report["selected_test"]["summary"],
                "individual_val_ndcg": raw,
                "llm": report["llm_evaluation"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
