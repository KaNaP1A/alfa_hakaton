"""Additional long-query probes after the closed run; evaluation only, never a new holdout."""

import json
from pathlib import Path

from audit_ranking import pooled_metrics, stability
from build_challenge import TASKS
from catboost import CatBoostRanker

from alfa_reco.bundle import atomic_json, sha256
from alfa_reco.relevance import RelevanceBackend
from alfa_reco.search import SearchEngine
from alfa_reco.suggestions import validate_query


def main():
    root = Path("artifacts/challenge_v2")
    manifest = json.loads((root / "manifest.json").read_text())
    target = root / "stress_report.json"
    if target.exists():
        raise ValueError("Stress report already exists; preserve the first evaluation")
    rows = []
    for n, (domain, goal, _alias, contrast, audience) in enumerate(TASKS):
        shared = {"family": f"task-{n:02d}", "domain": domain}
        rows.extend(
            [
                {
                    **shared,
                    "type": "long_permutation",
                    "queries": [
                        f"Ищу практический материал: как {goal} для {audience}. "
                        "Хочу понятную последовательность действий и разбор задачи. "
                        "Можно статью, курс или вебинар; формат сейчас не важен.",
                        "Формат сейчас не важен: можно статью, курс или вебинар. "
                        "Хочу понятную последовательность действий и разбор задачи. "
                        f"Ищу практический материал: как {goal} для {audience}.",
                    ],
                },
                {
                    **shared,
                    "type": "explicit_exclusion",
                    "queries": [
                        f"Моя задача — {goal} для {audience}. "
                        f"Сейчас не требуется {contrast}. "
                        "Ищу материал именно по первой задаче, с понятным объяснением действий."
                    ],
                },
                {
                    **shared,
                    "type": "distracting_context",
                    "queries": [
                        f"Коллеги обсуждали, как {TASKS[(n + 17) % len(TASKS)][1]}; "
                        "это фон, а не мой запрос. "
                        f"Мне нужно разобраться, как {goal} для {audience}. "
                        "Материал должен помогать именно моей задаче."
                    ],
                },
            ]
        )
    for row in rows:
        for query in row["queries"]:
            validate_query(query)
    cases = root / "stress_cases.jsonl"
    with cases.open("x", encoding="utf-8") as file:
        for n, row in enumerate(rows):
            row["id"] = f"long-stress-{n:03d}"
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    engine = SearchEngine(root / "catalog")
    backend = RelevanceBackend(engine, root / "index", require_model=False)
    model = Path("artifacts/relevance_v1/training/ranker.cbm")
    assert sha256(model) == manifest["frozen_model"], "Frozen model changed"
    backend.model = CatBoostRanker()
    backend.model.load_model(str(model))
    backend.policy = json.loads(model.with_name("manifest.json").read_text())["policy"]
    engine._relevance = backend
    results = []
    for row in rows:
        grades = {
            item["entity_key"]: (3 if item["oracle_audience"] == "primary" else 1)
            if item["oracle_family"] == row["family"] and item["oracle_goal"] == "primary"
            else 0
            for item in engine.catalog
        }
        outputs = [engine.search(q, mode="relevance") for q in row["queries"]]
        orders = [[r["entity_key"] for r in out["results"]] for out in outputs]
        top_correct = all(order and grades[order[0]] == 3 for order in orders)
        same = stability(*orders) if len(orders) == 2 else None
        passed = bool(top_correct and (same is None or same["exact_order"]))
        results.append(
            {
                **row,
                "passed": passed,
                "top_correct": bool(top_correct),
                "stability": same,
                "metrics": [pooled_metrics(order, grades) for order in orders],
                "top5": [
                    [
                        {"title": i["title"], "grade": grades[i["entity_key"]]}
                        for i in out["results"]
                    ]
                    for out in outputs
                ],
            }
        )
    report = {
        "scenarios": len(rows),
        "query_texts": sum(len(row["queries"]) for row in rows),
        "families": len(TASKS),
        "passed": sum(r["passed"] for r in results),
        "failed": sum(not r["passed"] for r in results),
        "by_type": {
            kind: {
                "n": sum(r["type"] == kind for r in results),
                "passed": sum(r["type"] == kind and r["passed"] for r in results),
                "correct_top": sum(r["type"] == kind and r["top_correct"] for r in results),
            }
            for kind in sorted({row["type"] for row in rows})
        },
        "model_sha256": sha256(model),
        "cases_sha256": sha256(cases),
        "runner_sha256": sha256(Path(__file__)),
        "results": results,
        "limits": (
            "Additional probes created after the main closed run, not a fresh holdout. "
            "Controlled fictional documents and structured labels. No training or policy tuning. "
            "Failures are retained; real-catalog usefulness still needs human review."
        ),
    }
    atomic_json(target, report)
    manifest["supplementary_stress"] = {
        k: v for k, v in report.items() if k not in {"results", "limits"}
    }
    atomic_json(root / "manifest.json", manifest)
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))


if __name__ == "__main__":
    main()
