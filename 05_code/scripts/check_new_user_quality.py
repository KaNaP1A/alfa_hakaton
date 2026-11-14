"""Inspect held-out scope examples and exploratory uncertainty signals; no gold claims."""

import json
import time
from pathlib import Path

from alfa_reco.cli import atomic_json
from alfa_reco.search import SearchEngine


def main():
    engine = SearchEngine("artifacts/catalog", semantic=True, llm_enabled=False)
    cases = json.loads(Path("evaluation/coverage_probe_cases.json").read_text())["cases"]
    rows = []
    for case in cases:
        start = time.perf_counter()
        result = engine.search(case["query"], mode="ensemble")
        rows.append(
            {
                **case,
                "confidence": result["confidence"],
                "coverage": result["coverage"],
                "first_title": result["results"][0]["title"] if result["results"] else None,
                "elapsed_ms": round((time.perf_counter() - start) * 1000, 1),
            }
        )
    summary = {
        label: {
            "n": sum(x["likely"] == label for x in rows),
            "uncertain": sum(
                x["likely"] == label and x["confidence"]["status"] == "uncertain" for x in rows
            ),
        }
        for label in ("present", "absent")
    }
    elapsed = sorted(x["elapsed_ms"] for x in rows)
    atomic_json(
        Path("evaluation/uncertainty_2026_11_12.json"),
        {
            "description": "Проверка разработчика, предварительные метки, не независимый gold; порог разработан на этом наборе.",
            "summary": summary,
            "latency_ms": {
                "n": len(elapsed),
                "p50": elapsed[(len(elapsed) - 1) // 2],
                "p95": elapsed[int((len(elapsed) - 1) * 0.95)],
            },
            "results": rows,
        },
    )
    holdout = json.loads(Path("evaluation/uncertainty_holdout_2026_11_12.json").read_text())[
        "cases"
    ]
    held_rows = []
    for case in holdout:
        result = engine.search(case["query"], mode="ensemble")
        held_rows.append(
            {
                **case,
                "confidence": result["confidence"],
                "coverage": result["coverage"],
                "first_title": result["results"][0]["title"] if result["results"] else None,
            }
        )
    held_summary = {
        label: {
            "n": sum(x["likely"] == label for x in held_rows),
            "uncertain": sum(
                x["likely"] == label and x["confidence"]["status"] == "uncertain" for x in held_rows
            ),
        }
        for label in ("present", "absent")
    }
    atomic_json(
        Path("evaluation/uncertainty_holdout_report_2026_11_12.json"),
        {
            "description": "Заранее зафиксированные разработчиком предположительные метки; не независимая экспертная разметка.",
            "summary": held_summary,
            "results": held_rows,
        },
    )
    negcases = json.loads(Path("evaluation/negative_heldout.json").read_text())["cases"]
    negatives = []
    for case in negcases:
        result = engine.search(case["query"], mode="ensemble")
        rule = result["query_rules"]
        observed = (
            "contrast"
            if rule["contrast_applied"]
            else "unresolved"
            if rule["unresolved_negation"]
            else "plain"
        )
        negatives.append(
            {
                **case,
                "observed": observed,
                "matches_expectation": observed == case["expected"],
                "rules": rule,
                "top5": [item["title"] for item in result["results"]],
            }
        )
    atomic_json(
        Path("evaluation/negative_2026_11_12.json"),
        {
            "description": "Ручные ожидания разработчика про обнаружение, а не оценка релевантности. Требуется независимая проверка всей пятерки.",
            "n": len(negatives),
            "matched": sum(x["matches_expectation"] for x in negatives),
            "results": negatives,
        },
    )
    print(
        json.dumps(
            {
                "coverage": summary,
                "heldout": held_summary,
                "latency": elapsed[(len(elapsed) - 1) // 2],
                "negation_matches": sum(x["matches_expectation"] for x in negatives),
                "negation_total": len(negatives),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
