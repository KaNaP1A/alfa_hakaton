"""Select on isolated synthetic validation; evaluate the frozen choice once on test."""

import argparse
import json
from pathlib import Path

import numpy as np
from audit_ranking import family_average, pooled_metrics
from catboost import CatBoostRanker
from compare_score_fusions import grid, normalize, readlines

from alfa_reco.bundle import atomic_json, sha256
from alfa_reco.eligibility import USER_KINDS
from alfa_reco.query_rules import exclusion_multiplier, intent_multiplier, plan_query
from alfa_reco.relevance import RelevanceBackend, build_index
from alfa_reco.search import SearchEngine
from alfa_reco.text import embedding_query, tokens

ROOT = Path("artifacts/synthetic_holdout_v3")
NAMES = ["bm25", "minilm", "e5", "catboost"]


def check_data(manifest):
    for name, digest in manifest["hashes"].items():
        if sha256(ROOT / name) != digest:
            raise ValueError("Frozen dataset changed: " + name)
    if sha256(Path("artifacts/relevance_v1/training/ranker.cbm")) != manifest["ranker_sha256"]:
        raise ValueError("Frozen ranker changed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["validation", "test"], required=True)
    parser.add_argument("--unlock-test", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "manifest.json").read_text())
    check_data(manifest)
    if args.split == "validation" and (ROOT / "selection.json").exists():
        raise ValueError(
            "Selection already frozen; create a fresh dataset for another tuning cycle"
        )
    if args.split == "test":
        if not args.unlock_test or manifest["test_status"] != "sealed_not_evaluated":
            raise ValueError("Test is sealed or already used")
        selection = json.loads((ROOT / "selection.json").read_text())
        if selection["evaluator_sha256"] != sha256(Path(__file__)):
            raise ValueError("Evaluator changed after selection")
        if selection["model_sha256"] != manifest["ranker_sha256"]:
            raise ValueError("Selected model changed")
        if selection["dataset_hashes"] != manifest["hashes"]:
            raise ValueError("Dataset changed after selection")
        manifest["test_status"] = "evaluation_started_no_retry"
        atomic_json(ROOT / "manifest.json", manifest)
    cases = readlines(ROOT / args.split / "queries.jsonl")
    lrows = readlines(ROOT / args.split / "labels.jsonl")
    labels = {x["id"]: set(x["positive"]) for x in lrows}
    if len(labels) != len(cases) or set(labels) != {c["id"] for c in cases}:
        raise ValueError("Mismatched query labels")
    engine = SearchEngine(ROOT / args.split / "catalog")
    real = SearchEngine("artifacts/catalog", semantic=True)
    encoder_path = json.loads(Path("artifacts/relevance_v1/training/manifest.json").read_text())[
        "encoder_path"
    ]
    index = ROOT / args.split / "index"
    if not (index / "manifest.json").exists():
        build_index(engine, encoder_path, index)
    backend = RelevanceBackend(engine, index, require_model=False)
    backend.model = CatBoostRanker()
    backend.model.load_model("artifacts/relevance_v1/training/ranker.cbm")
    backend.policy = json.loads(Path("artifacts/relevance_v1/training/manifest.json").read_text())[
        "policy"
    ]
    backend.canonical = True
    engine._relevance = backend
    minidoc = real.encoder.encode(
        [i["title"] + ". " + i["description"] for i in engine.catalog],
        normalize_embeddings=True,
        batch_size=32,
        show_progress_bar=False,
    )
    miniquery = real.encoder.encode(
        [embedding_query(c["query"]) for c in cases],
        normalize_embeddings=True,
        batch_size=32,
        show_progress_bar=False,
    )
    e5query = backend.encode_queries([c["query"] for c in cases])
    allweights = (
        grid() if args.split == "validation" else [tuple(selection["weights"][k] for k in NAMES)]
    )
    grouped = [[] for _ in allweights]
    baseline = []
    checks = 0
    details = []
    allowed = {i for i, item in enumerate(engine.catalog) if item["kind"] in USER_KINDS}
    oldprepare, oldscore = backend.prepare, backend.score
    for number, (case, mv, ev) in enumerate(zip(cases, miniquery, e5query, strict=True), 1):
        query = case["query"]
        prep = oldprepare(query, vector=ev)
        ids = prep["candidates"]
        plan = plan_query(query)
        mini = minidoc @ mv
        cols = [
            np.asarray(prep["lexical"])[ids],
            mini[ids],
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
        candidate_ids = set(ids) | set(priority)
        mult = {
            i: exclusion_multiplier(engine.retriever.title_terms[i], plan.excluded_terms)
            * intent_multiplier(engine.catalog[i]["title"], plan)
            for i in candidate_ids
        }
        admitted = {
            i: backend.support(prep, i, conflict=mult[i] < 1)["admitted"] for i in candidate_ids
        }
        use_rules = bool(plan.excluded_terms or plan.retention_expansion or plan.debt_expansion)

        def fast(order, *, apply=use_rules, mult=mult, priority=priority, admitted=admitted):
            if apply:
                prior = {i: r + 1 for r, i in enumerate(order)}
                order = sorted(
                    order,
                    key=lambda i: (
                        -mult[i] / (engine.ranking_config.rrf_k + prior[i]),
                        engine.catalog[i]["entity_key"],
                    ),
                )
            return [
                engine.catalog[i]["entity_key"]
                for i in list(dict.fromkeys(priority + order))[:60]
                if admitted[i]
            ][:5]

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
            return oldprepare(q, allowed, selected_keys, vector)

        backend.prepare = cached
        backend.score = oldscore
        actual = [x["entity_key"] for x in engine.search(query, mode="relevance")["results"]]
        ranking, _ = oldscore(prep)
        if fast(ranking) != actual:
            raise AssertionError("Baseline does not match serving")
        checks += 1
        target = labels[case["id"]]
        alllabels = {x["entity_key"]: 3 if x["entity_key"] in target else 0 for x in engine.catalog}
        if len(target) != 2 or not target <= alllabels.keys():
            raise ValueError("Invalid target IDs")
        baseline.append({"family": case["family"], "metrics": pooled_metrics(actual, alllabels)})
        selected_output = None
        for i, w in enumerate(allweights):
            vals = signals @ np.asarray(w)
            scores = {k: float(v) for k, v in zip(ids, vals, strict=True)}
            order = sorted(ids, key=lambda k: (-scores[k], engine.catalog[k]["entity_key"]))
            out = fast(order)
            grouped[i].append({"family": case["family"], "metrics": pooled_metrics(out, alllabels)})
            if args.split == "test" or i in {0, 10, 50, 100, 200, 285}:

                def score(_, *, order=order, scores=scores):
                    return order, scores

                backend.score = score
                direct = [
                    x["entity_key"] for x in engine.search(query, mode="relevance")["results"]
                ]
                if direct != out:
                    raise AssertionError("Accelerated result differs from serving")
                checks += 1
            if args.split == "test":
                selected_output = out
        backend.score = oldscore
        if args.split == "test":
            details.append(
                {
                    "id": case["id"],
                    "family": case["family"],
                    "baseline": actual,
                    "selected": selected_output,
                }
            )
        if number % 10 == 0:
            print(args.split, number, "/", len(cases), "verified", checks, flush=True)
    results = [
        {"weights": dict(zip(NAMES, w, strict=True)), "metrics": family_average(rows)}
        for w, rows in zip(allweights, grouped, strict=True)
    ]
    base = family_average(baseline)
    common = {
        "split": args.split,
        "cases": len(cases),
        "families": len({c["family"] for c in cases}),
        "baseline": base,
        "serving_equivalence_checks": checks,
        "labels": "Binary synthetic: 3 for two manually designated positive cards, 0 for the rest. No independent human review.",
        "limits": "Synthetic text is assistant-authored; family split is manually curated, no proof of semantic independence or pretraining exclusion; separate indexes avoid cross-split corpus statistics. Weights optimize this synthetic setup, not proven optimal on real catalog.",
    }
    if args.split == "validation":
        chosen = max(
            results,
            key=lambda r: (
                r["metrics"]["ndcg5_pooled"] if r["metrics"]["ndcg5_pooled"] is not None else -1,
                tuple(-r["weights"][n] for n in NAMES),
            ),
        )
        report = {
            **common,
            "configurations": len(results),
            "grid_step": 0.1,
            "trials": results,
            "selected": chosen,
        }
        atomic_json(ROOT / "validation_report.json", report)
        selection = {
            "weights": chosen["weights"],
            "selected_only_by": "family-average validation NDCG@5; deterministic tie break",
            "validation_report_sha256": sha256(ROOT / "validation_report.json"),
            "model_sha256": manifest["ranker_sha256"],
            "dataset_hashes": manifest["hashes"],
            "evaluator_sha256": sha256(Path(__file__)),
            "method": "min-max on retrieved candidates, weighted sum, existing candidate generation and admission policy; no fit on test",
        }
        atomic_json(ROOT / "selection.json", selection)
        print(
            json.dumps(
                {"baseline": base, "selected": chosen, "checks": checks},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        report = {
            **common,
            "frozen_weights": selection["weights"],
            "selected_metrics": results[0]["metrics"],
            "details": details,
        }
        atomic_json(ROOT / "test_report.json", report)
        manifest["test_status"] = "evaluated_once_no_further_tuning"
        manifest["test_report_sha256"] = sha256(ROOT / "test_report.json")
        atomic_json(ROOT / "manifest.json", manifest)
        print(
            json.dumps(
                {k: v for k, v in report.items() if k != "details"}, ensure_ascii=False, indent=2
            )
        )


if __name__ == "__main__":
    main()
