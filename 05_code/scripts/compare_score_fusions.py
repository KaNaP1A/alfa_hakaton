"""Offline score-grid comparison on judged pools; never installs a serving configuration."""

import itertools
import json
import re
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from audit_ranking import family_average, pooled_metrics
from catboost import CatBoostRanker

from alfa_reco.bundle import atomic_json, sha256
from alfa_reco.relevance import RelevanceBackend
from alfa_reco.search import SearchEngine

ROOT = Path("artifacts/challenge_v2")
NAMES = ["bm25", "minilm", "e5", "catboost"]


def readlines(p):
    return [json.loads(s) for s in p.read_text().splitlines() if s]


def normalize(v):
    lo, hi = float(np.min(v)), float(np.max(v))
    return (v - lo) / (hi - lo) if hi > lo else np.zeros_like(v)


def grid():
    return [
        tuple(v / 10 for v in a) for a in itertools.product(range(11), repeat=4) if sum(a) == 10
    ]


def evaluate(rows, weights):
    groups = defaultdict(list)
    for row in rows:
        scores = row["values"] @ np.asarray(weights)
        order = [
            row["keys"][i]
            for i in sorted(range(len(scores)), key=lambda i: (-scores[i], row["keys"][i]))
        ]
        groups[row["split"]].append(
            {"family": row["family"], "metrics": pooled_metrics(order, row["labels"])}
        )
    return {split: family_average(values) for split, values in groups.items()}


def main():
    started = time.time()
    engine = SearchEngine("artifacts/catalog", semantic=True)
    rb = engine.relevance_backend()
    pooldir = Path("artifacts/annotation_pool/relevance_v1")
    pool_manifest = json.loads((pooldir / "manifest.json").read_text())
    draft_manifest = json.loads((pooldir / "automatic_qwen/manifest.json").read_text())
    challenge_manifest = json.loads((ROOT / "manifest.json").read_text())
    if sha256(pooldir / "pool.jsonl") != pool_manifest["hashes_before_review"]["pool.jsonl"]:
        raise ValueError("Frozen real pool changed")
    if (
        sha256(pooldir / "pool.jsonl") != draft_manifest["pool_sha256"]
        or sha256(pooldir / "automatic_qwen/ratings.jsonl") != draft_manifest["ratings_sha256"]
    ):
        raise ValueError("Automatic labels do not match their recorded pool or manifest")
    for name in ("dev.jsonl", "oracle_dev.jsonl", "test.jsonl"):
        if sha256(ROOT / name) != challenge_manifest["hashes"][name]:
            raise ValueError(f"Frozen challenge file changed: {name}")
    if sha256(rb.path / "ranker.cbm") != challenge_manifest["frozen_model"]:
        raise ValueError("Model differs from the frozen challenge model")
    pool = readlines(pooldir / "pool.jsonl")
    drafts = {
        (r["query_id"], r["entity_key"]): r["grade"]
        for r in readlines(pooldir / "automatic_qwen/ratings.jsonl")
    }
    by_id = {x["entity_key"]: i for i, x in enumerate(engine.catalog)}
    query_texts = [q["query"] for q in pool]
    e5vec = rb.encode_queries(query_texts)
    from alfa_reco.text import embedding_query

    minivec = engine.encoder.encode(
        [embedding_query(q) for q in query_texts],
        normalize_embeddings=True,
        batch_size=32,
        show_progress_bar=False,
    )
    rows = []
    for n, (case, ev, mv) in enumerate(zip(pool, e5vec, minivec, strict=True), 1):
        cards = [c for c in case["candidates"] if c["kind"] != "glossary"]
        ids = [by_id[c["entity_key"]] for c in cards]
        labels = {c["entity_key"]: drafts.get((case["query_id"], c["entity_key"])) for c in cards}
        if not ids or any(type(x) is not int for x in labels.values()):
            continue
        prep = rb.prepare(case["query"], allowed=ids, vector=ev)
        raw = engine.vectors @ mv
        mini = np.zeros(len(engine.catalog), dtype=np.float32)
        if engine.units is None:
            mini = raw
        else:
            for mask in engine.unit_masks.values():
                np.maximum.at(mini, engine.unit_indices[mask], raw[mask])
        columns = [
            np.asarray(prep["lexical"])[ids],
            mini[ids],
            np.asarray(prep["e5"]["card"])[ids],
            rb.model.predict(prep["features"][ids]),
        ]
        rows.append(
            {
                "keys": [c["entity_key"] for c in cards],
                "values": np.stack([normalize(c) for c in columns], axis=1),
                "labels": labels,
                "family": case["family"],
                "split": case["split"],
            }
        )
        if n % 25 == 0:
            print("Real pool", n, "/", len(pool), flush=True)
    weights = grid()
    trials = [
        {"weights": dict(zip(NAMES, w, strict=True)), "real": evaluate(rows, w)} for w in weights
    ]
    usable = [t for t in trials if t["real"].get("validation", {}).get("ndcg5_pooled") is not None]
    selected = max(
        usable,
        key=lambda t: (
            t["real"]["validation"]["ndcg5_pooled"],
            tuple(-t["weights"][k] for k in NAMES),
        ),
    )
    # Existing synthetic test was already revealed: use only dev as a diagnostic, never tune on it.
    cases = [c for c in readlines(ROOT / "dev.jsonl") if c["type"] in ("retrieval", "contrast")]
    oracle = {r["id"]: r["labels"] for r in readlines(ROOT / "oracle_dev.jsonl")}
    synthetic = SearchEngine(ROOT / "catalog")
    sb = RelevanceBackend(synthetic, ROOT / "index", require_model=False)
    sb.model = CatBoostRanker()
    sb.model.load_model(str(rb.path / "ranker.cbm"))
    texts = [x["title"] + " " + x["description"] for x in synthetic.catalog]
    synthetic_minidoc = engine.encoder.encode(
        texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False
    )
    evec = sb.encode_queries([c["query"] for c in cases])
    mvec = engine.encoder.encode(
        [embedding_query(c["query"]) for c in cases],
        normalize_embeddings=True,
        batch_size=32,
        show_progress_bar=False,
    )
    synrows = []
    for n, (case, ev, mv) in enumerate(zip(cases, evec, mvec, strict=True), 1):
        ids = [
            i
            for i, c in enumerate(synthetic.catalog)
            if not case.get("kind") or c["kind"] == case["kind"]
        ]
        prep = sb.prepare(case["query"], allowed=ids, vector=ev)
        raw = synthetic_minidoc @ mv
        cols = [
            np.asarray(prep["lexical"])[ids],
            raw[ids],
            np.asarray(prep["e5"]["card"])[ids],
            sb.model.predict(prep["features"][ids]),
        ]
        keys = [synthetic.catalog[i]["entity_key"] for i in ids]
        synrows.append(
            {
                "keys": keys,
                "values": np.stack([normalize(c) for c in cols], axis=1),
                "labels": {k: oracle[case["id"]][k] for k in keys},
                "family": case["family"],
                "split": "dev",
            }
        )
        if n % 80 == 0:
            print("Synthetic dev", n, "/", len(cases), flush=True)
    for trial, w in zip(trials, weights, strict=True):
        trial["synthetic_dev"] = evaluate(synrows, w)["dev"]
    training = json.loads(
        Path("artifacts/relevance_v1/training/synthetic_queries.json").read_text()
    )

    def normalize_query(text):
        return " ".join(re.findall(r"[а-яa-z0-9]+", text.casefold().replace("ё", "е")))

    original_cases = json.loads(Path("evaluation/ensemble_cases_v2.json").read_text())["queries"]
    trainset = {normalize_query(r["query"]) for r in training}
    trainset.update(normalize_query(r["query"]) for r in original_cases if r["split"] == "train")
    train_targets = {r["target"] for r in training}
    test = readlines(ROOT / "test.jsonl")
    testtexts = [
        q for r in test for q in (r.get("queries") or ([r["query"]] if "query" in r else []))
    ]
    overlaps = sorted({q for q in testtexts if normalize_query(q) in trainset})
    identity = [r for r in test if r["type"] == "real_identity"]
    trajectories = [r for r in test if r["type"] == "recommendation_real"]
    result = {
        "components": NAMES,
        "weights_grid_step": 0.1,
        "configurations": len(trials),
        "nonempty_component_combinations": 15,
        "selection_rule": "Maximum family-average NDCG@5 on 6 real automatic validation queries, tie-break fixed; no synthetic or test selection.",
        "selected": selected["weights"],
        "real_rows": len(rows),
        "synthetic_dev_rows": len(synrows),
        "input_hashes": {
            "pool": sha256(pooldir / "pool.jsonl"),
            "automatic_ratings": sha256(pooldir / "automatic_qwen/ratings.jsonl"),
            "synthetic_dev": sha256(ROOT / "dev.jsonl"),
            "synthetic_dev_oracle": sha256(ROOT / "oracle_dev.jsonl"),
            "synthetic_test_queries_for_overlap_audit_only": sha256(ROOT / "test.jsonl"),
            "ranker": sha256(rb.path / "ranker.cbm"),
        },
        "leakage_audit": {
            "test_texts": len(testtexts),
            "queries_checked": len(training) + sum(r["split"] == "train" for r in original_cases),
            "normalized_exact_query_matches": overlaps,
            "real_identity_test_cases": len(identity),
            "real_identity_training_target_matches": sum(
                r["target"] in train_targets for r in identity
            ),
            "recommendation_test_cases": len(trajectories),
            "recommendation_cases_with_training_target": sum(
                any(k in train_targets for k in r["viewed"]) for r in trajectories
            ),
        },
        "trials": trials,
        "seconds": round(time.time() - started, 1),
        "limits": "Diagnostic candidate-pool reranking only, not end-to-end serving final_score; min-max scores within each candidate pool, no admission gate. Real pool labels are automated, historical and previously observed; pool excludes glossary consistently. Validation contains only 6 queries and selection is unstable; test has been observed and is not independent. Synthetic dev uses all 280 fictional documents with labels generated from task templates; MiniLM fictional embeddings use title plus description, not the production unit index. Synthetic labels and text are templated and often contain the answer and synonym. Existing synthetic test was not reused. Weights are discrete nonnegative grid, not all real-valued weights; no production installation.",
    }
    output = Path("artifacts/fusion_comparison_v2")
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(output / "report.json", result)
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "trials"}, ensure_ascii=False, indent=2
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
