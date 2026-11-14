"""Evaluate existing partial judgments against the actual search API without LLM."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from ensemble_experiment import average, metrics

from alfa_reco.cli import atomic_json
from alfa_reco.search import SearchEngine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists")
    cases = json.loads(Path("evaluation/ensemble_cases_v2.json").read_text())["queries"]
    engine = SearchEngine("artifacts/catalog", semantic=True, llm_enabled=False)
    rows = []
    for index, case in enumerate(cases):
        result = engine.search(case["query"], mode="ensemble", top=50)
        order = [x["entity_key"] for x in result["results"]]
        labels = {row["entity_key"]: row["grade"] for row in case["judgments"]}
        result_metrics = metrics(order, labels)
        result_metrics["mrr50_pooled"] = result_metrics.pop("mrr60_pooled")
        rows.append(
            {
                "id": case["id"],
                "family": case["family"],
                "split": case["split"],
                "query": case["query"],
                "coverage": result["coverage"],
                "metrics": result_metrics,
                "top5": [
                    {
                        "id": r["entity_key"],
                        "title": r["title"],
                        "grade": labels.get(r["entity_key"]),
                    }
                    for r in result["results"][:5]
                ],
            }
        )
        if (index + 1) % 40 == 0:
            print(f"{index + 1}/{len(cases)}", flush=True)
    summary = {}
    for split in ("train", "val", "test"):
        groups = defaultdict(list)
        for row in rows:
            if row["split"] == split:
                groups[row["family"]].append(row["metrics"])
        summary[split] = {
            "queries": sum(len(x) for x in groups.values()),
            "families": len(groups),
            "metrics": average([average(x) for x in groups.values()]),
        }
    report = {
        "cases": len(rows),
        "catalog_sha256": engine.manifest["catalog_sha256"],
        "summary": summary,
        "caveat": "Existing assistant-labeled synthetic data, previously observed test, 4 judgments per query; unjudged treated as zero and metrics biased.",
        "results": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, report)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
