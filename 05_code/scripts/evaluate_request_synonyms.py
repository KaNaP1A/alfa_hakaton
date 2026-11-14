"""Diagnostic comparison of the previously used synonym pairs, not relevance judgments."""

import argparse
import json
import statistics
from pathlib import Path

from alfa_reco.search import SearchEngine


def evaluate(catalog, cases):
    pairs = [row for row in json.loads(cases.read_text(encoding="utf-8"))["pairs"]
             if row["type"] == "synonym"]
    engine = SearchEngine(catalog, semantic=False, llm_enabled=False)
    rows = []
    for number, pair in enumerate(pairs, 1):
        orders = [
            [item["entity_key"] for item in engine.search(query, mode="relevance", top=5)["results"]]
            for query in pair["queries"]
        ]
        left, right = map(set, orders)
        union = left | right
        rows.append({
            "queries": pair["queries"], "orders": orders,
            "both_nonempty": bool(left and right),
            "same_order": orders[0] == orders[1],
            "jaccard": len(left & right) / len(union) if union else None,
        })
        print(f"Checked pair {number}/{len(pairs)}", flush=True)
    return {
        "generation": engine.generation,
        "pairs": len(rows),
        "both_nonempty": sum(row["both_nonempty"] for row in rows),
        "same_order_nonempty": sum(row["same_order"] and row["both_nonempty"] for row in rows),
        "empty_both": sum(row["jaccard"] is None for row in rows),
        "mean_jaccard_nonempty_union": statistics.mean(
            row["jaccard"] for row in rows if row["jaccard"] is not None
        ) if any(row["jaccard"] is not None for row in rows) else None,
        "limitations": "Previously observed, assistant-authored approximate synonym pairs; overlap is not relevance or equivalence validation.",
        "results": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("artifacts/catalog"))
    parser.add_argument("--cases", type=Path, default=Path("evaluation/robustness_cases.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Output already exists")
    result = evaluate(args.catalog, args.cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(f"Saved {len(result['results'])} pairs to {args.output}")


if __name__ == "__main__":
    main()
