"""Collect top results for targeted cases with either version of the search engine."""

import argparse
import json
from pathlib import Path

from alfa_reco.cli import atomic_json
from alfa_reco.search import SearchEngine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True)
    args = parser.parse_args()
    cases = json.loads(Path("evaluation/query_rules_cases.json").read_text())["cases"]
    engine = SearchEngine("artifacts/catalog", semantic=True)
    rows = []
    for case in cases:
        result = engine.search(case["query"], top=5)
        rows.append(
            {
                **case,
                "rules": result.get("query_rules"),
                "top5": [{"id": r["entity_key"], "title": r["title"]} for r in result["results"]],
            }
        )
    atomic_json(Path(args.results), {"cases": len(rows), "results": rows})
    print(f"{len(rows)} cases saved to {args.results}")


if __name__ == "__main__":
    main()
