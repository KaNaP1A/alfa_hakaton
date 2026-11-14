"""Train and evaluate query-material relevance locally on CPU, with explicit pair provenance.

Unknown candidates never receive a relevance grade. Synthetic data contributes
low-weight source-over-sampled-item preferences only. Independent human training
is reported as unavailable until both reviewers have resolved the supplied pool.
"""

import argparse
import hashlib
import itertools
import json
import os
import random
import shutil
import statistics
import tempfile
import time
from collections import Counter
from pathlib import Path

import numpy as np
from audit_ranking import bootstrap_delta, family_average, pooled_metrics, stability, validate_cases
from catboost import CatBoostRanker, Pool
from generate_local_relevance_queries import eligible_sources

from alfa_reco.bundle import atomic_json, load_bundle, sha256
from alfa_reco.evaluation import resolved_grade
from alfa_reco.relevance import FEATURES, RelevanceBackend, build_index, code_hashes
from alfa_reco.search import SearchEngine
from alfa_reco.storage import output_lock
from alfa_reco.synthetic import description_candidate, title_candidates
from alfa_reco.text import words

ACTIVE_OUTPUT = None


def training_source_for_regime(regime):
    """Describe the fitted pool, rather than all groups prepared for the sweep."""
    if regime == "synthetic_only":
        return "weak_pairs_with_provisional_weight_scaling"
    if regime == "provisional_only":
        return "provisional_assistant_only"
    if regime in {"mixed_0.3", "mixed_1.0"}:
        return "provisional_assistant_and_weak_source_preferences"
    raise ValueError("Unknown training regime")


def update_job(output, **values):
    path = output / "job.json"
    previous = json.loads(path.read_text()) if path.exists() else {}
    atomic_json(path, {**previous, **values, "updated_unix": time.time(), "pid": os.getpid()})


def weak_queries(catalog, cases, local_path, limit=700, seed=42):
    eligible = eligible_sources(catalog, cases, seed)
    ids = {i["entity_key"] for i in eligible}
    rows = []
    if local_path and local_path.exists():
        for line in local_path.read_text().splitlines():
            row = json.loads(line)
            if (
                row["target"] not in ids
                or row.get("split") != "train"
                or row.get("label") is not None
            ):
                raise ValueError(
                    "Synthetic source crosses protected split or invents relevance grades"
                )
            rows.append({**row, "source": "local_model"})
    for item in sorted(
        eligible, key=lambda i: hashlib.sha256(i["entity_key"].encode()).hexdigest()
    ):
        candidates = [
            (kind, text)
            for kind, _, text in title_candidates(item["title"], item["kind"], seed)
            if kind in {"short_fragment", "typo_transposition"}
        ]
        description = description_candidate(item)
        if description:
            candidates.append(("description_problem", description))
        for kind, text in candidates:
            if 15 <= len(text) <= 300:
                rows.append(
                    {
                        "query": text,
                        "target": item["entity_key"],
                        "source": kind,
                        "source_kind": item["kind"],
                        "split": "train",
                        "label": None,
                        "label_status": "weak_source_preference_not_relevance_grade",
                    }
                )
    seen = {" ".join(words(c["query"])) for c in cases}
    result = []
    for row in rows:
        key = " ".join(words(row["query"]))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
        if len(result) >= limit:
            break
    return result


def resolved_human_pool(path):
    if path is None or not path.exists():
        return [], {"available": False, "reason": "No resolved independent human judgments"}
    pool = [json.loads(line) for line in (path / "pool.jsonl").read_text().splitlines() if line]
    ratings_path = path / "judgments_merged.jsonl"
    if not ratings_path.exists():
        ratings_path = path / "judgments.jsonl"
    ratings = [json.loads(line) for line in ratings_path.read_text().splitlines() if line]
    grades = {(r["query_id"], r["entity_key"]): resolved_grade(r) for r in ratings}
    rows = []
    for row in pool:
        known = [
            {"entity_key": c["entity_key"], "grade": grades.get((row["query_id"], c["entity_key"]))}
            for c in row["candidates"]
        ]
        if (
            row["split"] == "train"
            and len(known) >= 2
            and all(c["grade"] is not None for c in known)
        ):
            rows.append(
                {
                    "id": "human:" + row["query_id"],
                    "query": row["query"],
                    "family": "human:" + row["family"],
                    "split": "train",
                    "judgments": known,
                }
            )
    return rows, {
        "available": bool(rows),
        "resolved_train_queries": len(rows),
        "source_sha256": sha256(ratings_path),
        "reason": None if rows else "Pool exists but independent judgments are unresolved",
    }


def make_pool(groups, weak_scale=0.0, synthetic_only=False):
    features, labels, ids, pairs, weights = [], [], [], [], []
    explicit_total = sum(sum(g["pair_weights"]) for g in groups if g["source"] != "synthetic")
    weak_total = sum(sum(g["pair_weights"]) for g in groups if g["source"] == "synthetic")
    for group_id, group in enumerate(groups):
        if synthetic_only and group["source"] != "synthetic":
            continue
        if group["source"] == "synthetic" and not weak_scale:
            continue
        multiplier = (
            weak_scale * explicit_total / max(weak_total, 1e-12)
            if group["source"] == "synthetic"
            else 1.0
        )
        offset = len(features)
        features.extend(group["features"])
        # CatBoost requires a target column; unknowns have a numerical placeholder
        # only. Explicit pairs below are the ENTIRE supervision for PairLogit.
        labels.extend([0 if grade is None else grade for grade in group["grades"]])
        ids.extend([group_id] * len(group["features"]))
        pairs.extend([(offset + a, offset + b) for a, b in group["pairs"]])
        weights.extend([w * multiplier for w in group["pair_weights"]])
    if not pairs:
        raise ValueError("No valid training preferences")
    return Pool(
        np.asarray(features, dtype=np.float32),
        labels,
        group_id=ids,
        pairs=pairs,
        pairs_weight=weights,
        feature_names=FEATURES,
    )


def prepare_training(backend, cases, synthetic, output, seed=42):
    index = {row["entity_key"]: i for i, row in enumerate(backend.engine.catalog)}
    protected = {j["entity_key"] for row in cases for j in row["judgments"]}
    train = [c for c in cases if c["split"] == "train"]
    family_sizes = Counter(c["family"] for c in train)
    groups = []
    for case in train:
        prepared = backend.prepare(case["query"])
        judged = case["judgments"]
        columns = [index[j["entity_key"]] for j in judged]
        pairs, weights = [], []
        for a, b in itertools.permutations(range(len(judged)), 2):
            if judged[a]["grade"] > judged[b]["grade"]:
                pairs.append((a, b))
                weights.append(
                    (2 ** judged[a]["grade"] - 2 ** judged[b]["grade"])
                    / family_sizes[case["family"]]
                )
        if pairs:
            groups.append(
                {
                    "features": prepared["features"][columns],
                    "grades": [j["grade"] for j in judged],
                    "pairs": pairs,
                    "pair_weights": weights,
                    "source": "provisional_assistant",
                    "query": case["query"],
                    "entity_keys": [j["entity_key"] for j in judged],
                }
            )
    rng = random.Random(seed)
    vectors = backend.encode_queries([row["query"] for row in synthetic]) if synthetic else []
    accepted = []
    for number, (row, vector) in enumerate(zip(synthetic, vectors, strict=True), 1):
        prepared = backend.prepare(row["query"], vector=vector)
        target = index[row["target"]]
        # Filter obviously ungrounded generated questions; this remains a weak check.
        if prepared["e5"]["card"][target] < 0.76:
            continue
        source_subject = backend.retriever.context_terms[target]
        other = [
            i
            for i in prepared["candidates"]
            if backend.engine.catalog[i]["entity_key"] not in protected
            and i != target
            and prepared["e5"]["card"][i] < prepared["e5"]["card"][target] - 0.015
        ]
        hard = other[:3]
        easy = [i for i in other[3:] if not source_subject & backend.retriever.title_terms[i]]
        sampled = hard + rng.sample(easy, min(3, len(easy)))
        if not sampled:
            continue
        chosen = [target] + sampled
        groups.append(
            {
                "features": prepared["features"][chosen],
                "grades": [None] * len(chosen),
                "pairs": [(0, i) for i in range(1, len(chosen))],
                "pair_weights": [1 / len(sampled)] * len(sampled),
                "source": "synthetic",
                "query": row["query"],
                "entity_keys": [backend.engine.catalog[i]["entity_key"] for i in chosen],
            }
        )
        accepted.append(row)
        if number % 100 == 0:
            print("Prepared weak source preferences", number, "/", len(synthetic), flush=True)
    with (output / "training_preferences.jsonl").open("x", encoding="utf-8") as file:
        for g in groups:
            file.write(
                json.dumps({k: v for k, v in g.items() if k != "features"}, ensure_ascii=False)
                + "\n"
            )
    atomic_json(output / "synthetic_queries.json", accepted)
    return groups


def evaluate(engine, cases):
    rows = []
    for case in cases:
        result = engine.search(case["query"], mode="relevance")
        labels = {j["entity_key"]: j["grade"] for j in case["judgments"]}
        keys = [r["entity_key"] for r in result["results"]]
        prepared = engine.relevance_backend().prepare(case["query"])
        candidates = {engine.catalog[i]["entity_key"] for i in prepared["candidates"]}
        positive = {key for key, grade in labels.items() if grade >= 2}
        rows.append(
            {
                "id": case["id"],
                "family": case["family"],
                "query": case["query"],
                "metrics": pooled_metrics(keys, labels),
                "candidate_recall_judged": len(candidates & positive) / max(len(positive), 1),
                "top5": [
                    {
                        "key": r["entity_key"],
                        "title": r["title"],
                        "grade": labels.get(r["entity_key"]),
                    }
                    for r in result["results"]
                ],
            }
        )
    return {
        "summary": family_average(rows),
        "rows": rows,
        "candidate_recall_judged": statistics.mean(r["candidate_recall_judged"] for r in rows),
    }


def no_answer(engine, cases):
    rows = []
    for case in cases:
        result = engine.search(case["query"], mode="relevance")
        rows.append(
            {
                **case,
                "returned": len(result["results"]),
                "titles": [i["title"] for i in result["results"]],
            }
        )
    return {
        "rows": rows,
        "assumed_absent_returned": sum(r["likely"] == "absent" and r["returned"] > 0 for r in rows),
        "assumed_present_empty": sum(r["likely"] == "present" and not r["returned"] for r in rows),
    }


def evaluate_stability(engine):
    dataset = json.loads(Path("evaluation/robustness_cases.json").read_text())["pairs"]
    rows = []
    for case in dataset:
        results = [engine.search(q, mode="relevance") for q in case["queries"]]
        a, b = [[i["entity_key"] for i in p["results"]] for p in results]
        rows.append(
            {
                **case,
                **stability(a, b),
                "first_titles": [i["title"] for i in results[0]["results"]],
                "second_titles": [i["title"] for i in results[1]["results"]],
            }
        )
    summary = {}
    for kind in sorted({r["type"] for r in rows}):
        subset = [r for r in rows if r["type"] == kind]
        numeric = [r["jaccard5"] for r in subset if r["jaccard5"] is not None]
        summary[kind] = {
            "pairs": len(subset),
            "exact_order": sum(r["exact_order"] for r in subset),
            "same_set": sum(r["same_set"] for r in subset),
            "both_empty": sum(r["both_empty"] for r in subset),
            "mean_jaccard": statistics.mean(numeric) if numeric else None,
        }
    return {"summary": summary, "rows": rows}


def install(engine, source):
    with output_lock(engine.path.parent):
        active, manifest, _ = load_bundle(engine.path.parent)
        if active != engine.path or manifest["catalog_sha256"] != engine.manifest["catalog_sha256"]:
            raise ValueError("Catalog changed during training")
        root = active / "relevance"
        root.mkdir(exist_ok=True)
        generation = "model-" + sha256(source / "manifest.json")[:16]
        destination = root / generation
        if not destination.exists():
            with tempfile.TemporaryDirectory(dir=root) as tmp:
                stage = Path(tmp) / "bundle"
                stage.mkdir()
                for name in [
                    "manifest.json",
                    "vectors.npz",
                    "normalized_catalog.json",
                    "ranker.cbm",
                ]:
                    shutil.copy2(source / name, stage / name)
                os.replace(stage, destination)
        atomic_json(root / "CURRENT.json", {"generation": generation})
        return str(destination)


def main():
    global ACTIVE_OUTPUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="artifacts/catalog")
    parser.add_argument("--index", type=Path, default=Path("artifacts/relevance_v1/index"))
    parser.add_argument(
        "--encoder", type=Path, default=Path("artifacts/models/multilingual-e5-small")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--local-queries", type=Path)
    parser.add_argument("--fixed-config-from-report", type=Path,
                        help="Reuse a previously selected model configuration and policy without tuning")
    parser.add_argument("--synthetic-limit", type=int, default=700)
    parser.add_argument(
        "--human-pool", type=Path, default=Path("artifacts/annotation_pool/complex_v3")
    )
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    ACTIVE_OUTPUT = args.output
    update_job(args.output, status="running", stage="loading", started_unix=time.time())
    cases_path = Path("evaluation/ensemble_cases_v2.json")
    cases = json.loads(cases_path.read_text())["queries"]
    engine = SearchEngine(args.catalog, semantic=False, llm_enabled=False)
    validate_cases(cases, engine.catalog)
    if not (args.index / "manifest.json").exists():
        build_index(engine, args.encoder, args.index)
    backend = RelevanceBackend(engine, args.index, require_model=False)
    engine._relevance = backend
    synthetic = weak_queries(engine.catalog, cases, args.local_queries, args.synthetic_limit)
    human, human_status = resolved_human_pool(args.human_pool)
    if human:
        raise ValueError(
            "Resolved human data found: create a unified split manifest before combining independent query families"
        )
    print("Human supervision", human_status, flush=True)
    print(
        "Synthetic candidates", len(synthetic), Counter(r["source"] for r in synthetic), flush=True
    )
    update_job(args.output, stage="preparing_training")
    groups = prepare_training(backend, cases, synthetic, args.output)
    # Cache evaluation features only, with their exact candidate filters. Training
    # never reads validation/test labels; only final evaluation sees test labels.
    original_prepare = backend.prepare
    cache = {}
    all_allowed = frozenset(
        i for i, item in enumerate(engine.catalog) if item["kind"] != "glossary"
    )

    def cached_prepare(query, allowed=None, selected_keys=(), vector=None):
        key = (
            query,
            backend.canonical,
            None
            if allowed is None or frozenset(allowed) == all_allowed
            else tuple(sorted(allowed)),
        )
        if selected_keys or vector is not None:
            return original_prepare(query, allowed, selected_keys, vector)
        if key not in cache:
            if len(cache) > 600:
                cache.clear()
            cache[key] = original_prepare(query, allowed)
        return cache[key]

    backend.prepare = cached_prepare
    validation = [c for c in cases if c["split"] == "val"]
    calibration_probes = json.loads(Path("evaluation/coverage_probe_cases.json").read_text())[
        "cases"
    ]
    trials, models = [], {}
    best = None
    # Mixed weights express total synthetic preference mass relative to known
    # provisional preferences; increasing the number of copies cannot dominate.
    regimes = [
        ("provisional_only", 0.0, False),
        ("mixed_0.3", 0.3, False),
        ("mixed_1.0", 1.0, False),
        ("synthetic_only", 1.0, True),
    ]
    depths, l2_values = [3, 5, 6], [3, 10]
    fixed = None
    if args.fixed_config_from_report:
        fixed = json.loads(args.fixed_config_from_report.read_text())
        selection = fixed["selected"]
        regimes = [row for row in regimes if row[0] == selection["regime"]]
        if (len(regimes) != 1 or selection["depth"] not in depths
                or selection["l2_leaf_reg"] not in l2_values
                or selection["iterations"] != 400 or selection["canonical"] is not True):
            raise ValueError("Unsupported fixed configuration")
        depths, l2_values = [selection["depth"]], [selection["l2_leaf_reg"]]
    for canonical, regime, depth, l2 in itertools.product([True], regimes, depths, l2_values):
        regime_name, ratio, synthetic_only = regime
        backend.canonical = canonical
        pool = make_pool(groups, ratio, synthetic_only)
        name = f"{regime_name}_d{depth}_l2{l2}"
        model = CatBoostRanker(
            iterations=400,
            depth=depth,
            learning_rate=0.04,
            loss_function="PairLogit",
            l2_leaf_reg=l2,
            random_seed=42,
            thread_count=2,
            verbose=False,
            allow_writing_files=False,
            allow_const_label=True,
        )
        update_job(args.output, stage="training", trial=name, trials_completed=len(trials))
        model.fit(pool)
        backend.model = model
        metrics = evaluate(engine, validation)
        trial = {
            "name": name,
            "regime": regime_name,
            "canonical": canonical,
            "synthetic_weight_ratio": ratio,
            "depth": depth,
            "l2_leaf_reg": l2,
            "iterations": model.tree_count_,
            "validation": metrics["summary"],
        }
        trials.append(trial)
        models[name] = model
        print(
            "Trial",
            name,
            "validation NDCG@5",
            round(metrics["summary"]["ndcg5_pooled"], 6),
            flush=True,
        )
        key = (metrics["summary"]["ndcg5_pooled"], -ratio, -depth, -l2)
        if best is None or key > best[0]:
            best = (key, trial)
        atomic_json(args.output / "trials.json", trials)
    chosen = best[1]
    backend.model = models[chosen["name"]]
    backend.canonical = chosen["canonical"]
    policy_trials = []
    update_job(args.output, stage="gate_calibration", selected_model=chosen["name"])
    policy_grid = itertools.product([0.76, 0.80, 0.84], [0.84, 0.88, 0.92], [0.65, 0.85])
    if fixed:
        p = fixed["policy"]
        policy_grid = [(p["semantic_min"], p["strong_semantic_min"], p["lexical_min"])]
    for semantic, strong, lexical in policy_grid:
        backend.policy = {
            "semantic_min": semantic,
            "strong_semantic_min": strong,
            "lexical_min": lexical,
        }
        metrics = evaluate(engine, validation)["summary"]
        probes = no_answer(engine, calibration_probes)
        policy_trials.append(
            {
                "policy": dict(backend.policy),
                "validation": metrics,
                "calibration_absent_returned": probes["assumed_absent_returned"],
                "calibration_present_empty": probes["assumed_present_empty"],
            }
        )
    policy_trials.sort(
        key=lambda t: (
            t["calibration_absent_returned"] > 1,
            -t["validation"]["ndcg5_pooled"],
            t["calibration_absent_returned"],
            -t["policy"]["semantic_min"],
            -t["policy"]["strong_semantic_min"],
        )
    )
    backend.policy = policy_trials[0]["policy"]
    update_job(args.output, stage="final_evaluation")
    metrics = {
        split: evaluate(engine, [c for c in cases if c["split"] == split])
        for split in ("train", "val", "test")
    }
    baseline = json.loads(Path("evaluation/audit_release/report.json").read_text())
    stability_result = evaluate_stability(engine)
    heldout_probes = json.loads(Path("evaluation/uncertainty_holdout_2026_11_12.json").read_text())[
        "cases"
    ]
    report = {
        "catalog_sha256": engine.manifest["catalog_sha256"],
        "cases_sha256": sha256(cases_path),
        "feature_names": FEATURES,
        "fixed_configuration_report_sha256": sha256(args.fixed_config_from_report)
        if args.fixed_config_from_report else None,
        "source_hashes": code_hashes(),
        "human_supervision": human_status,
        "selected": chosen,
        "policy": backend.policy,
        "training_groups": dict(Counter(g["source"] for g in groups)),
        "training_rows": sum(len(g["features"]) for g in groups),
        "explicit_pair_preferences": sum(
            len(g["pairs"]) for g in groups if g["source"] != "synthetic"
        ),
        "weak_source_preferences": sum(
            len(g["pairs"]) for g in groups if g["source"] == "synthetic"
        ),
        "trials": trials,
        "policy_trials": policy_trials,
        "quality": metrics,
        "baselines": {
            mode: {split: baseline["quality"][mode][split]["summary"] for split in ("val", "test")}
            for mode in ("hybrid", "catboost", "ensemble")
        },
        "test_ndcg_delta_vs_hybrid": bootstrap_delta(
            baseline["quality"]["hybrid"]["test"]["rows"], metrics["test"]["rows"]
        ),
        "robustness": stability_result,
        "no_answer_old_holdout": no_answer(engine, heldout_probes),
        "calibration_guard_passed": policy_trials[0]["calibration_absent_returned"] <= 1,
        "limits": "No resolved human labels; assistant-authored judgments, four documents/query, previously observed test, pooled metrics treat unjudged as 0. Synthetic candidates remain unknown relevance; training uses low-weight weak pair preferences, not invented negative grades. No blind test or conversion claim. Stability regressions are evaluated only after model/policy selection, not used to select trials.",
    }
    for name in ["manifest.json", "vectors.npz", "normalized_catalog.json"]:
        shutil.copy2(args.index / name, args.output / name)
    backend.model.save_model(str(args.output / "ranker.cbm"))
    meta = json.loads((args.output / "manifest.json").read_text())
    meta.update(
        ranker_sha256=sha256(args.output / "ranker.cbm"),
        canonical=backend.canonical,
        policy=backend.policy,
        trained_on=training_source_for_regime(chosen["regime"]),
        selected=chosen,
        cases_sha256=sha256(cases_path),
        source_hashes=code_hashes(),
        training_preferences_sha256=sha256(args.output / "training_preferences.jsonl"),
    )
    atomic_json(args.output / "manifest.json", meta)
    if args.install:
        report["installed_experimental_bundle"] = install(engine, args.output)
        report["default_changed"] = False
    atomic_json(args.output / "report.json", report)
    update_job(
        args.output,
        status="complete",
        stage="complete",
        selected=chosen["name"],
        trials_completed=len(trials),
    )
    print(
        json.dumps(
            {
                "selected": chosen,
                "policy": backend.policy,
                "test": metrics["test"]["summary"],
                "robustness": stability_result["summary"],
                "installed": report.get("installed_experimental_bundle"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        if ACTIVE_OUTPUT is not None:
            update_job(
                ACTIVE_OUTPUT, status="failed", stage="failed", error_type=type(error).__name__
            )
        raise
