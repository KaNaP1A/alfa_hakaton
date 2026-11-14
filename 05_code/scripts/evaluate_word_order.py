"""Evaluate stability on manually authored, meaning-preserving query pairs."""

import argparse
import json
from pathlib import Path

from alfa_reco.cli import atomic_json
from alfa_reco.search import SearchEngine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=Path("evaluation/word_order_cases.json"))
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists")
    data = json.loads(args.cases.read_text())
    engine = SearchEngine("artifacts/catalog", semantic=True, llm_enabled=False)
    rows = []
    for first, second in data["pairs"]:
        a = engine.search(first, mode="ensemble", top=5)
        b = engine.search(second, mode="ensemble", top=5)
        one = [row["entity_key"] for row in a["results"]]
        two = [row["entity_key"] for row in b["results"]]
        union = set(one) | set(two)
        rows.append(
            {
                "first": first,
                "second": second,
                "exact_order": one == two,
                "same_set": set(one) == set(two),
                "jaccard5": len(set(one) & set(two)) / len(union) if union else 1.0,
                "first_titles": [x["title"] for x in a["results"]],
                "second_titles": [x["title"] for x in b["results"]],
            }
        )
    result = {
        "pairs": len(rows),
        "same_order": sum(x["exact_order"] for x in rows),
        "same_set": sum(x["same_set"] for x in rows),
        "mean_jaccard5": sum(x["jaccard5"] for x in rows) / len(rows),
        "caveat": "Сравнивает только зафиксированные пары; LLM отключена. Не всякая перестановка сохраняет смысл.",
        "results": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, result)
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "results"}, ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
