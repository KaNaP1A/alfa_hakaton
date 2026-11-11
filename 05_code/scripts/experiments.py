"""Small, explicit, judged-pool experiment; not a production quality estimate."""

import itertools
import json
import math
from dataclasses import asdict
from pathlib import Path

import numpy as np
from catboost import CatBoostRanker, Pool

from alfa_reco.retrieval import FEATURE_NAMES, RankingConfig
from alfa_reco.search import SearchEngine


def metrics(order, labels):
    grades = [labels.get(key, 0) for key in order[:5]]
    ideal = sorted(labels.values(), reverse=True)[:5]

    def dcg(values):
        return sum((2**v - 1) / math.log2(i + 2) for i, v in enumerate(values))

    positive = {key for key, value in labels.items() if value > 0}
    return {
        "ndcg5_pooled": dcg(grades) / dcg(ideal) if dcg(ideal) else 0,
        "recall60_judged": len(set(order[:60]) & positive) / max(len(positive), 1),
        "judged_at_5": sum(key in labels for key in order[:5]) / 5,
    }


def main():
    dataset = json.loads(Path("evaluation/judgments.json").read_text())
    queries = dataset["queries"]
    families = {}
    for q in queries:
        if families.setdefault(q["family"], q["split"]) != q["split"]:
            raise ValueError("Family leakage")
    engine = SearchEngine("artifacts/catalog", semantic=True)
    ids = {row["entity_key"]: i for i, row in enumerate(engine.catalog)}
    for q in queries:
        keys = [item["entity_key"] for item in q["judgments"]]
        if len(set(keys)) != len(keys) or any(key not in ids for key in keys):
            raise ValueError("Invalid judgment")
    print("Preparing", len(queries), "queries", flush=True)
    qvec = engine.encoder.encode(
        [q["query"] for q in queries], normalize_embeddings=True, batch_size=32
    )
    sims = engine.vectors @ qvec.T
    prepared = []
    for col, q in enumerate(queries):
        dense = {
            s: np.zeros(len(engine.catalog), dtype=np.float32) for s in ("card", "body", "lesson")
        }
        for source, mask in engine.unit_masks.items():
            np.maximum.at(dense[source], engine.unit_indices[mask], sims[mask, col])
        prepared.append(
            (q, engine.retriever.signals(q["query"], {k: v.tolist() for k, v in dense.items()}))
        )

    def evaluate(cfg, split, model=None):
        outcomes = []
        for q, signals in prepared:
            if q["split"] != split:
                continue
            ranks, *_ = engine.retriever.rank(signals, cfg)
            if model is not None and ranks:
                values = model.predict(np.asarray([signals["features"][i] for i in ranks]))
                ranks = [i for _, i in sorted(zip(-values, ranks, strict=True))]
            labels = {j["entity_key"]: j["grade"] for j in q["judgments"]}
            outcomes.append(metrics([engine.catalog[i]["entity_key"] for i in ranks], labels))
        return {
            key: round(sum(item[key] for item in outcomes) / len(outcomes), 5)
            for key in outcomes[0]
        }

    print("Testing 108 validation configurations", flush=True)
    trials = []
    for title, facet, dense, body in itertools.product(
        [1.0, 2.0, 4.0], [0.0, 0.5, 1.0, 2.0], [0.5, 1.0, 2.0], [0.0, 0.25, 0.75]
    ):
        cfg = RankingConfig(
            title=title, topics=facet, tags=facet, industries=facet, dense_weight=dense, body=body
        )
        trials.append({"parameters": asdict(cfg), "validation": evaluate(cfg, "val")})
    trials.sort(
        key=lambda x: (
            -x["validation"]["ndcg5_pooled"],
            json.dumps(x["parameters"], sort_keys=True),
        )
    )
    best = RankingConfig(**trials[0]["parameters"])
    # Tune the three metadata weights independently, with all other choices fixed.
    category_trials = []
    for topic, tag, industry in itertools.product([0.0, 0.5, 1.0, 2.0], repeat=3):
        params = {**asdict(best), "topics": topic, "tags": tag, "industries": industry}
        cfg = RankingConfig(**params)
        category_trials.append({"parameters": params, "validation": evaluate(cfg, "val")})
    category_trials.sort(
        key=lambda row: (
            -row["validation"]["ndcg5_pooled"],
            json.dumps(row["parameters"], sort_keys=True),
        )
    )
    best = RankingConfig(**category_trials[0]["parameters"])
    features = []
    labels = []
    groups = []
    for q, signals in prepared:
        if q["split"] == "train":
            for row in q["judgments"]:
                features.append(signals["features"][ids[row["entity_key"]]])
                labels.append(row["grade"])
                groups.append(q["id"])
    model = CatBoostRanker(
        iterations=250,
        depth=4,
        learning_rate=0.05,
        loss_function="YetiRank",
        random_seed=42,
        thread_count=2,
        verbose=False,
        allow_writing_files=False,
    )
    model.fit(Pool(features, labels, group_id=groups, feature_names=FEATURE_NAMES))
    base = RankingConfig()
    report = {
        "queries": len(queries),
        "families": len(families),
        "split_counts": {
            s: sum(q["split"] == s for q in queries) for s in ("train", "val", "test")
        },
        "assessor": dataset["assessor"],
        "judgments_per_query": 4,
        "baseline_validation": evaluate(base, "val"),
        "selected_validation": evaluate(best, "val"),
        "baseline_test": evaluate(base, "test"),
        "selected_test": evaluate(best, "test"),
        "catboost_validation": evaluate(best, "val", model),
        "catboost_test": evaluate(best, "test", model),
        "note": "Pooled NDCG treats unjudged as 0; judged coverage is reported. Tiny assistant-labeled set, not production evidence.",
    }
    out = Path("evaluation/results")
    out.mkdir(parents=True, exist_ok=True)
    (out / "weight_trials.json").write_text(json.dumps(trials, ensure_ascii=False, indent=2))
    (out / "category_trials.json").write_text(
        json.dumps(category_trials, ensure_ascii=False, indent=2)
    )
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (out / "selected_config.json").write_text(
        json.dumps(
            {
                "parameters": asdict(best),
                "chosen_on": "validation pooled NDCG@5",
                "catalog_sha256": engine.manifest["catalog_sha256"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    model.save_model(str(out / "catboost.cbm"))
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
