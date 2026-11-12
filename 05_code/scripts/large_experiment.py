"""Weak-label retrieval benchmark. Synthetic title-derived queries are not real search logs."""

import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

import numpy as np
from catboost import CatBoostRanker, Pool

from alfa_reco.bundle import atomic_json, load_bundle, sha256
from alfa_reco.eligibility import USER_KINDS
from alfa_reco.query_rules import plan_query
from alfa_reco.retrieval import FEATURE_NAMES
from alfa_reco.search import SearchEngine
from alfa_reco.storage import output_lock
from alfa_reco.text import embedding_query, tokens

# Feature ablations exclude identifiers, user data, and the untrained selection signal.
PROFILES = {
    "minimal": [
        "bm25_title",
        "bm25_description",
        "cosine_card",
        "query_coverage",
        "title_coverage",
    ],
    "content": [
        "bm25_title",
        "bm25_description",
        "bm25_body",
        "bm25_lessons",
        "cosine_card",
        "cosine_body",
        "cosine_lesson",
        "query_coverage",
        "title_coverage",
    ],
    "full_no_selection": [name for name in FEATURE_NAMES if name != "selection_match"],
}


def build_queries(catalog, excluded_targets=frozenset()):
    candidates = []
    seen = set()
    seen_queries = set()
    for item in sorted(catalog, key=lambda x: x["entity_key"]):
        if item["entity_key"] in excluded_targets:
            continue
        words = re.findall(r"[\w+#]+", item["title"], flags=re.UNICODE)
        normalized = " ".join(tokens(item["title"]))
        # Avoid identical normalized titles crossing splits; keep the first source.
        if len(words) < 3 or len(normalized) < 10 or normalized in seen:
            continue
        seen.add(normalized)
        query = " ".join(words[: min(6, len(words))])
        query_key = " ".join(tokens(query))
        if query_key in seen_queries:
            continue
        seen_queries.add(query_key)
        digest = hashlib.sha256(normalized.encode()).hexdigest()
        bucket = int(digest[:8], 16) % 10
        split = "train" if bucket < 7 else "validation" if bucket < 8 else "test"
        # A shortened title approximates an incomplete query; it is not a human request.
        candidates.append(
            {
                "query_id": digest[:16],
                "query": query,
                "target": item["entity_key"],
                "kind": item["kind"],
                "split": split,
                "source": "title_fragment",
            }
        )
        title_terms = set(tokens(item["title"]))
        description_words = re.findall(r"[\w+#]+", item.get("description", ""), flags=re.UNICODE)
        hint_words = [
            word
            for word in description_words
            if tokens(word) and not (set(tokens(word)) & title_terms)
        ]
        hint = " ".join(hint_words[:12])
        hint_key = " ".join(tokens(hint))
        if len(hint_words) >= 4 and hint_key not in seen_queries:
            seen_queries.add(hint_key)
            candidates.append(
                {
                    "query_id": digest[:16] + "d",
                    "query": hint,
                    "target": item["entity_key"],
                    "kind": item["kind"],
                    "split": split,
                    "source": "description_without_title_words",
                }
            )
    return candidates


def ranked_metrics(queries, prediction_order, candidate_ids, k=10):
    reciprocal, hit, candidate_hit = [], [], []
    by_kind = defaultdict(list)
    by_source = defaultdict(list)
    for row, order, candidates in zip(queries, prediction_order, candidate_ids, strict=True):
        target = row["target"]
        candidate_hit.append(float(target in candidates))
        top = [candidates[i] for i in order[:k]]
        value = 1 / (top.index(target) + 1) if target in top else 0
        reciprocal.append(value)
        hit.append(float(value > 0))
        by_kind[row["kind"]].append(value)
        by_source[row["source"]].append(value)
    return {
        "queries": len(queries),
        "mrr_at_10": round(float(np.mean(reciprocal)), 6),
        "target_hit_at_10": round(float(np.mean(hit)), 6),
        "candidate_recall": round(float(np.mean(candidate_hit)), 6),
        "mrr_by_kind": {
            k: {"n": len(v), "mrr": round(float(np.mean(v)), 6)} for k, v in sorted(by_kind.items())
        },
        "mrr_by_source": {
            k: {"n": len(v), "mrr": round(float(np.mean(v)), 6)}
            for k, v in sorted(by_source.items())
        },
    }


def install_small(output, engine, ranker, feature_names, model_name):
    """Publish a model only for the unchanged input snapshot; metadata commits last."""
    with output_lock(output):
        active, manifest, _ = load_bundle(output)
        if (
            active != engine.path
            or manifest["catalog_sha256"] != engine.manifest["catalog_sha256"]
            or manifest.get("semantic", {}).get("vectors_sha256")
            != engine.manifest["semantic"]["vectors_sha256"]
        ):
            raise ValueError("Catalog or embeddings changed during training")
        from alfa_reco.retrieval import RankingConfig

        config_path = active / "ranking_config.json"
        current = RankingConfig()
        if config_path.exists():
            data = json.loads(config_path.read_text())
            if data.get("catalog_sha256") != manifest["catalog_sha256"]:
                raise ValueError("Ranking configuration belongs to a different catalog")
            current = RankingConfig(**data["parameters"])
        if current != engine.ranking_config:
            raise ValueError("Ranking configuration changed during training")
        destination = active / "catboost_small.cbm"
        temp = active / "catboost_small.tmp.cbm"
        try:
            ranker.save_model(str(temp))
            os.replace(temp, destination)
        finally:
            temp.unlink(missing_ok=True)
        atomic_json(
            active / "catboost_small_meta.json",
            {
                "catalog_sha256": manifest["catalog_sha256"],
                "vectors_sha256": manifest["semantic"]["vectors_sha256"],
                "model_sha256": sha256(destination),
                "feature_names": feature_names,
                "retrieval_parameters": asdict(current),
                "experimental": True,
                "trained_on": "synthetic_title_description_fragments",
                "model_name": model_name,
            },
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/catalog")
    parser.add_argument("--result-dir", default="artifacts/large_experiment")
    parser.add_argument("--sample", type=int, default=2200)
    parser.add_argument(
        "--install-small",
        action="store_true",
        help="Install experimental five-feature model for the current catalog",
    )
    args = parser.parse_args()
    engine = SearchEngine(args.output, semantic=True)
    judged = json.loads(Path("evaluation/judgments.json").read_text())["queries"]
    protected_ids = {j["entity_key"] for q in judged for j in q["judgments"]}
    queries = build_queries(
        [item for item in engine.catalog if item["kind"] in USER_KINDS], protected_ids
    )
    queries = sorted(queries, key=lambda x: x["query_id"])[: args.sample]
    id_to_index = {item["entity_key"]: i for i, item in enumerate(engine.catalog)}
    config = engine.ranking_config
    allowed = {i for i, item in enumerate(engine.catalog) if item["kind"] in USER_KINDS}
    retrieval_queries = {q["query_id"]: plan_query(q["query"]).retrieval_query for q in queries}
    protected_targets = protected_ids | {q["target"] for q in queries if q["split"] != "train"}
    print(
        "Queries:", len(queries), "splits:", dict(Counter(q["split"] for q in queries)), flush=True
    )
    vectors = engine.encoder.encode(
        [embedding_query(retrieval_queries[q["query_id"]]) for q in queries],
        normalize_embeddings=True,
        batch_size=64,
        show_progress_bar=False,
    )
    rows = []
    for start in range(0, len(queries), 64):
        similarities = engine.vectors @ vectors[start : start + 64].T
        for column, row in enumerate(queries[start : start + 64]):
            dense = {
                source: np.zeros(len(engine.catalog), dtype=np.float32)
                for source in ("card", "body", "lesson")
            }
            for source, mask in engine.unit_masks.items():
                np.maximum.at(dense[source], engine.unit_indices[mask], similarities[mask, column])
            signals = engine.retriever.signals(
                retrieval_queries[row["query_id"]],
                {k: v.tolist() for k, v in dense.items()},
                config=config,
            )
            order, *_ = engine.retriever.rank(signals, config, allowed)
            # Fix candidate pool before training. Test/validation are never gold-injected.
            order = order[:60]
            if row["split"] == "train":
                order = [
                    i for i in order if engine.catalog[i]["entity_key"] not in protected_targets
                ]
                if id_to_index[row["target"]] not in order:
                    order.append(id_to_index[row["target"]])
            rows.append(
                {
                    "query": row,
                    "indices": order,
                    "features": np.asarray(
                        [signals["features"][i] for i in order], dtype=np.float32
                    ),
                }
            )
        print("prepared", min(start + 64, len(queries)), "/", len(queries), flush=True)
    models = {}
    val_results = []
    for profile, names in PROFILES.items():
        cols = [FEATURE_NAMES.index(name) for name in names]
        train = [r for r in rows if r["query"]["split"] == "train"]
        arrays = []
        labels = []
        groups = []
        for row in train:
            target = id_to_index[row["query"]["target"]]
            if len(row["indices"]) < 2:
                continue
            arrays.append(row["features"][:, cols])
            labels.extend([int(i == target) for i in row["indices"]])
            groups.extend([row["query"]["query_id"]] * len(row["indices"]))
        pool = Pool(np.vstack(arrays), labels, group_id=groups, feature_names=names)
        val = [r for r in rows if r["query"]["split"] == "validation"]
        for loss, depth in [("YetiRank", 3), ("YetiRank", 5), ("PairLogit", 3), ("PairLogit", 5)]:
            model = CatBoostRanker(
                iterations=200,
                depth=depth,
                learning_rate=0.05,
                loss_function=loss,
                random_seed=42,
                thread_count=2,
                verbose=False,
                allow_writing_files=False,
            )
            model.fit(pool)
            orders = [
                list(np.argsort(-model.predict(row["features"][:, cols]), kind="stable"))
                for row in val
            ]
            metrics = ranked_metrics(
                [r["query"] for r in val],
                orders,
                [[engine.catalog[i]["entity_key"] for i in r["indices"]] for r in val],
            )
            key = f"{profile}_{loss}_depth{depth}"
            models[key] = (model, cols)
            val_results.append({"model": key, "features": names, "validation": metrics})
            print(key, metrics["mrr_at_10"], flush=True)
    val_results.sort(key=lambda row: (-row["validation"]["mrr_at_10"], row["model"]))
    selected = val_results[0]["model"]
    test = [r for r in rows if r["query"]["split"] == "test"]
    candidates = [[engine.catalog[i]["entity_key"] for i in r["indices"]] for r in test]
    baseline = [list(range(len(r["indices"]))) for r in test]
    profile_best = {
        profile: next(row["model"] for row in val_results if row["model"].startswith(profile + "_"))
        for profile in PROFILES
    }
    test_by_profile = {}
    for profile, key in profile_best.items():
        model, cols = models[key]
        predicted = [
            list(np.argsort(-model.predict(r["features"][:, cols]), kind="stable")) for r in test
        ]
        test_by_profile[profile] = {
            "model": key,
            **ranked_metrics([r["query"] for r in test], predicted, candidates),
        }
    # The old manually reviewed set is not used in fitting or selection. Its
    # labels were previously observed, so it is a useful check, not a blind test.
    from experiments import metrics as pooled_metrics

    human_vectors = engine.encoder.encode(
        [embedding_query(plan_query(q["query"]).retrieval_query) for q in judged],
        normalize_embeddings=True,
        batch_size=32,
    )
    human_similarity = engine.vectors @ human_vectors.T
    human_outcomes = {"baseline": []} | {profile: [] for profile in PROFILES}
    for col, row in enumerate(judged):
        dense = {
            source: np.zeros(len(engine.catalog), dtype=np.float32)
            for source in ("card", "body", "lesson")
        }
        for source, mask in engine.unit_masks.items():
            np.maximum.at(dense[source], engine.unit_indices[mask], human_similarity[mask, col])
        signals = engine.retriever.signals(
            plan_query(row["query"]).retrieval_query,
            {k: v.tolist() for k, v in dense.items()},
            config=config,
        )
        order, *_ = engine.retriever.rank(signals, config, allowed)
        order = order[:60]
        labels = {entry["entity_key"]: entry["grade"] for entry in row["judgments"]}
        keys = [engine.catalog[i]["entity_key"] for i in order]
        human_outcomes["baseline"].append(pooled_metrics(keys, labels))
        for profile, key in profile_best.items():
            model, cols = models[key]
            predictions = model.predict(
                np.asarray([signals["features"][i] for i in order])[:, cols]
            )
            ranking = np.argsort(-predictions, kind="stable")
            human_outcomes[profile].append(pooled_metrics([keys[i] for i in ranking], labels))
    human_summary = {
        name: {
            metric: round(sum(r[metric] for r in outcomes) / len(outcomes), 6)
            for metric in outcomes[0]
        }
        for name, outcomes in human_outcomes.items()
    }
    result = {
        "schema_version": 1,
        "catalog_sha256": engine.manifest["catalog_sha256"],
        "source": "synthetic_title_and_description_fragments_not_real_queries",
        "warning": "Weak positives and sampled unjudged negatives. This measures known-target retrieval, not actual relevance or purchase. Test target IDs and manually judged item IDs excluded from training.",
        "split_counts": dict(Counter(q["split"] for q in queries)),
        "source_counts": dict(Counter(q["source"] for q in queries)),
        "validation_trials": val_results,
        "selected_model": selected,
        "baseline_test": ranked_metrics([r["query"] for r in test], baseline, candidates),
        "test_by_profile": test_by_profile,
        "manual_reviewed_58_not_blind": human_summary,
    }
    output = Path(args.result_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "queries.json").write_text(json.dumps(queries, ensure_ascii=False, indent=2))
    (output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    for profile, key in profile_best.items():
        models[key][0].save_model(str(output / (profile + ".cbm")))
    (output / "profile_best.json").write_text(
        json.dumps(profile_best, ensure_ascii=False, indent=2)
    )
    if args.install_small:
        name = profile_best["minimal"]
        install_small(args.output, engine, models[name][0], PROFILES["minimal"], name)
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in ("validation_trials",)},
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
