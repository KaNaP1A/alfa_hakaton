"""Execute individual scenarios; never train on or select parameters using the sealed test."""

import argparse
import json
import math
import time
from collections import defaultdict
from pathlib import Path

from audit_ranking import pooled_metrics, stability
from catboost import CatBoostRanker

from alfa_reco.bundle import atomic_json, sha256
from alfa_reco.personalization import recommend
from alfa_reco.relevance import RelevanceBackend, build_index
from alfa_reco.search import SearchEngine
from alfa_reco.suggestions import validate_query


def contract(engine, n):
    mode = n // 5
    v = n % 5

    def invalid(call):
        try:
            call()
        except (ValueError, TypeError):
            return
        raise AssertionError("Invalid input accepted")

    if mode == 0:
        invalid(lambda: engine.search("налоги", mode="relevance", top=[0, 51, True, 1.5, "5"][v]))
    elif mode == 1:
        invalid(lambda: validate_query("x" * (301 + v)))
    elif mode == 2:
        invalid(lambda: validate_query("налог" + chr(v) + "ИП"))
    elif mode == 3:
        invalid(lambda: engine.search("налоги", mode=["bad", "rank", "ml", "", None][v]))
    elif mode == 4:
        invalid(
            lambda: engine.search(
                "налоги",
                mode="relevance",
                kind=["glossary", "lesson", "pdf", "video", "unknown"][v],
            )
        )
    elif mode == 5:
        invalid(
            lambda: engine.search(
                "налоги", mode="relevance", selection_id="bad", selection_generation="old"
            )
        )
    elif mode == 6:
        invalid(lambda: recommend(engine.catalog, ["bad" + str(v)], []))
    elif mode == 7:
        invalid(lambda: recommend(engine.catalog, [], ["unknown:" + str(v)]))
    elif mode == 8:
        invalid(lambda: recommend(engine.catalog, [], [], limit=[0, 21, True, 1.5, "5"][v]))
    elif mode == 9:
        assert recommend(engine.catalog[: [0, 1, 3, 10, len(engine.catalog)][v]], [], []) == []
    elif mode == 10:
        invalid(lambda: recommend(engine.catalog, [], ["x"] * (51 + v)))
    elif mode == 11:
        cat = [
            {
                "entity_key": f"article:{i}",
                "kind": "article",
                "title": "Денежный поток компании",
                "description": "",
                "topics": ["Финансы"],
                "tags": [],
            }
            for i in range(40 + v)
        ]
        history = [i["entity_key"] for i in cat[: 30 + v]]
        out = recommend(cat, [], history, limit=10)
        assert not set(history) & {i["entity_key"] for i in out}, "Old viewed items reappeared"
    elif mode == 12:
        cat = [
            {
                "entity_key": "article:a",
                "kind": "article",
                "title": "Налоги бизнеса",
                "description": "",
                "topics": ["Финансы"],
                "tags": [],
            },
            {
                "entity_key": "article:b",
                "kind": "article",
                "title": "Продажи магазина",
                "description": "",
                "topics": ["Маркетинг"],
                "tags": [],
            },
        ]
        assert recommend(cat, [], ["article:a"]) == []
        assert recommend(cat, [], ["article:b"]) == []
    elif mode == 13:
        invalid(lambda: recommend(engine.catalog, [{}, "finance", 1, None, [None]][v], []))
    elif mode == 14:
        invalid(lambda: recommend(engine.catalog, [], [{}, "x", 1, None, [123]][v]))
    elif mode == 15:
        a = engine.search(
            [
                "Frontend",
                "React разработка",
                "Kubernetes кластер",
                "нейрохирургия",
                "астрофизика пульсаров",
            ][v],
            mode="relevance",
        )
        assert not a["results"], "Unsupported precise technical topic returned primary results"
    elif mode == 16:
        a = engine.search("налоги ИП", mode="relevance")
        assert all(math.isfinite(i["scores"]["final_score"]) for i in a["results"])
    elif mode == 17:
        a = engine.search("налоги ИП", mode="relevance")
        assert len({r["entity_key"] for r in a["results"]}) == len(a["results"])
    elif mode == 18:
        a = engine.search("налоги ИП", mode="relevance")
        assert all(not {"UserId", "IP", "source_sqlite"} & set(i) for i in a["results"])
    else:
        a = engine.search("налоги ИП", mode="relevance", top=v + 1)
        assert len(a["results"]) <= v + 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", type=Path, default=Path("artifacts/challenge_v2"))
    p.add_argument("--split", choices=["dev", "test"], required=True)
    p.add_argument("--unlock-test", action="store_true")
    a = p.parse_args()
    root = a.directory
    m = json.loads((root / "manifest.json").read_text())
    if a.split == "test" and not a.unlock_test:
        p.error("Test requires explicit --unlock-test after development is frozen")
    if a.split == "test" and m["test_status"] != "sealed_not_evaluated":
        p.error("Test already evaluated; create a new holdout before another selection cycle")
    for name in [a.split + ".jsonl", "oracle_" + a.split + ".jsonl"]:
        assert sha256(root / name) == m["hashes"][name], "Frozen data changed"
    rows = list(map(json.loads, (root / (a.split + ".jsonl")).read_text().splitlines()))
    oracle = {
        r["id"]: r["labels"]
        for r in map(json.loads, (root / ("oracle_" + a.split + ".jsonl")).read_text().splitlines())
    }
    real = SearchEngine("artifacts/catalog")
    rb = real.relevance_backend()
    synthetic = SearchEngine(root / "catalog")
    idx = root / "index"
    if not (idx / "manifest.json").exists():
        build_index(synthetic, rb.manifest["encoder_path"], idx)
    sb = RelevanceBackend(synthetic, idx, require_model=False)
    sb.model = CatBoostRanker()
    sb.model.load_model(str(rb.path / "ranker.cbm"))
    sb.policy = dict(rb.policy)
    synthetic._relevance = sb
    # Reuse exact features during the evaluation only; no per-test fitting.
    for backend in [rb, sb]:
        original = backend.prepare
        cache = {}

        def prepare(q, allowed=None, selected_keys=(), vector=None, orig=original, cache=cache):
            key = (q, None if allowed is None else tuple(sorted(allowed)))
            if selected_keys or vector is not None:
                return orig(q, allowed, selected_keys, vector)
            if key not in cache:
                if len(cache) > 400:
                    cache.clear()
                cache[key] = orig(q, allowed)
            return cache[key]

        backend.prepare = prepare
    results = []
    start = time.perf_counter()
    for number, case in enumerate(rows, 1):
        detail = {}
        passed = True
        error = None
        t = time.perf_counter()
        try:
            typ = case["type"]
            if typ in {"retrieval", "contrast", "no_answer"}:
                r = synthetic.search(case["query"], mode="relevance", kind=case.get("kind"))
                keys = [i["entity_key"] for i in r["results"]]
                labels = oracle.get(
                    case["id"], dict.fromkeys([i["entity_key"] for i in synthetic.catalog], 0)
                )
                metrics = pooled_metrics(keys, labels)
                detail = {
                    "metrics": metrics,
                    "top5": [
                        {
                            "key": i["entity_key"],
                            "title": i["title"],
                            "grade": labels[i["entity_key"]],
                        }
                        for i in r["results"]
                    ],
                }
                if typ == "no_answer":
                    assert not keys, "Primary answer returned for absent target"
                else:
                    assert keys and labels[keys[0]] == 3, (
                        "Top result does not fully match independently specified task"
                    )
            elif typ == "equivalence":
                out = [synthetic.search(q, mode="relevance") for q in case["queries"]]
                keys = [[i["entity_key"] for i in r["results"]] for r in out]
                detail = stability(*keys)
                if case["relation"] == "synonym":
                    assert detail["both_nonempty"] and detail["jaccard5"] >= 0.5, (
                        "Paraphrase lost majority overlap"
                    )
                else:
                    assert detail["both_nonempty"] and detail["exact_order"], (
                        "Meaning-preserving transformation changed the result"
                    )
            elif typ == "real_identity":
                r = real.search(case["query"], mode="relevance", kind=case["kind"])
                detail = {"top5": [i["title"] for i in r["results"]]}
                assert r["results"] and r["results"][0]["title"] == case["query"], (
                    "Known title missing at first position"
                )
            elif typ == "recommendation_real":
                if case.get("check") == "deduplicate":
                    # Real, distinct source cards; repeated events must not inflate interest.
                    one = recommend(
                        real.catalog,
                        case["categories"],
                        case["viewed"][:1],
                        vectors=rb.vectors["card"],
                    )
                    two = recommend(
                        real.catalog,
                        case["categories"],
                        case["viewed"],
                        vectors=rb.vectors["card"],
                    )
                    assert one == two
                    assert not set(case["viewed"]) & {i["entity_key"] for i in two}
                    detail = {
                        "trajectory": "real_repeated_view",
                        "returned": len(one),
                        "source_kind": case["source_kind"],
                        "usefulness_grade": None,
                    }
                else:
                    out = recommend(
                        real.catalog, case["categories"], case["viewed"], vectors=rb.vectors["card"]
                    )
                    assert not set(case["viewed"]) & {i["entity_key"] for i in out}
                    assert all(i["kind"] != "glossary" and i["reason"] for i in out)
                    detail = {
                        "returned": len(out),
                        "source_kind": case["source_kind"],
                        "titles": [i["title"] for i in out],
                        "usefulness_grade": None,
                    }
            else:
                contract(real, case["variant"])
        except (AssertionError, ValueError, TypeError, KeyError) as e:
            passed = False
            error = str(e)
        results.append(
            {
                "id": case["id"],
                "type": case["type"],
                "family": case["family"],
                "passed": passed,
                "error": error,
                "latency_ms": (time.perf_counter() - t) * 1000,
                **detail,
            }
        )
        if number % 100 == 0:
            print(
                "Scenarios",
                number,
                "/",
                len(rows),
                "failed",
                sum(not r["passed"] for r in results),
                flush=True,
            )
    groups = defaultdict(list)
    for r in results:
        if r.get("metrics", {}).get("ndcg5_pooled") is not None:
            groups[r["family"]].append(r["metrics"]["ndcg5_pooled"])
    metric = sum(sum(v) / len(v) for v in groups.values()) / len(groups) if groups else None
    report = {
        "split": a.split,
        "scenarios": len(results),
        "passed": sum(r["passed"] for r in results),
        "failed": sum(not r["passed"] for r in results),
        "by_type": {
            t: {
                "n": sum(r["type"] == t for r in results),
                "passed": sum(r["type"] == t and r["passed"] for r in results),
            }
            for t in sorted({r["type"] for r in results})
        },
        "fully_judged_synthetic_ndcg5": metric,
        "seconds": time.perf_counter() - start,
        "source_hashes": {
            str(p): sha256(p)
            for p in [
                *Path("src/alfa_reco").glob("*.py"),
                Path(__file__),
                Path("scripts/build_challenge.py"),
            ]
        },
        "frozen_model_sha256": sha256(rb.path / "ranker.cbm"),
        "results": results,
        "limits": "Independent structured labels within fictional corpus; frozen model transferred without fitting. Not human judgments or real-world NDCG. Personal recommendation usefulness on real data remains unjudged.",
    }
    atomic_json(root / (a.split + "_report.json"), report)
    if a.split == "test":
        m.update(
            test_status="evaluated_once_no_further_tuning",
            test_report_sha256=sha256(root / "test_report.json"),
        )
        atomic_json(root / "manifest.json", m)
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in {"results", "source_hashes"}},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
