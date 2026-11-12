"""Build a blinded candidate pool for independent human relevance judgments."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from alfa_reco.cli import sha256
from alfa_reco.search import SearchEngine
from alfa_reco.synthetic import digest, split_for
from alfa_reco.synthetic_scenarios import COMPLEX_FAMILIES


def jsonl(rows):
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)


def review_markdown(pool):
    def escape(value):
        value = str(value).replace("<", "&lt;").replace(">", "&gt;")
        return re.sub(r"([\\`*_{}\[\]()#!|])", r"\\\1", value)

    lines = [
        "# Пул кандидатов для проверки",
        "",
        "Карточки перемешаны. 0 — не относится; 1 — связана с темой; 2 — частично отвечает; 3 — прямо отвечает. ? — не знаю.",
        "Заполняйте reviewer_a/reviewer_b в judgments.jsonl; этот файл для чтения и не импортируется автоматически.",
        "",
    ]
    for number, row in enumerate(pool, 1):
        lines.extend(
            [f"## {number}. {escape(row['query'])}", "", f"ID запроса: {row['query_id']}", ""]
        )
        for item in row["candidates"]:
            lines.append(
                f"- [ ] 0 / 1 / 2 / 3 / ? — {escape(item['title'])} ({item['entity_key']})"
            )
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory")
    parser.add_argument("--limit", type=int, default=75)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists")
    if not 1 <= args.limit <= 500:
        parser.error("Invalid limit")
    engine = SearchEngine("artifacts/catalog", semantic=True, llm_enabled=False)
    queries = []
    for family, variants in sorted(COMPLEX_FAMILIES.items()):
        for query in variants:
            queries.append({"family": family, "query": query})
    queries = queries[: args.limit]
    pool, rankings, judgments = [], [], []
    for index, case in enumerate(queries):
        qid = digest("pool-v1:" + case["family"] + ":" + case["query"])[:24]
        rankings_by_method = {}
        candidates = {}
        coverage = None
        for method in ("bm25", "hybrid", "ensemble"):
            result = engine.search(case["query"], mode=method, top=5)
            rankings_by_method[method] = [item["entity_key"] for item in result["results"]]
            if method == "ensemble":
                coverage = result["coverage"]
            for item in result["results"]:
                candidates[item["entity_key"]] = {
                    "entity_key": item["entity_key"],
                    "title": item["title"],
                    "description": item["description"],
                    "kind": item["kind"],
                }
        ordered = sorted(
            candidates.values(), key=lambda x: digest(f"{args.seed}:{qid}:{x['entity_key']}")
        )
        group = "complex:" + digest(case["family"])[:24]
        pool.append(
            {
                "query_id": qid,
                "family": case["family"],
                "split": split_for(group, args.seed),
                "query": case["query"],
                "candidates": ordered,
            }
        )
        rankings.append({"query_id": qid, "rankings": rankings_by_method, "coverage": coverage})
        for item in ordered:
            judgments.append(
                {
                    "query_id": qid,
                    "entity_key": item["entity_key"],
                    "reviewer_a": None,
                    "reviewer_b": None,
                    "adjudicated": None,
                }
            )
        if (index + 1) % 15 == 0:
            print(f"{index + 1}/{len(queries)}", flush=True)
    args.output.mkdir(parents=True)
    hashes = {}
    for name, rows in [
        ("pool.jsonl", pool),
        ("rankings.jsonl", rankings),
        ("judgments.jsonl", judgments),
    ]:
        text = jsonl(rows)
        with (args.output / name).open("x", encoding="utf-8") as f:
            f.write(text)
        hashes[name] = hashlib.sha256(text.encode()).hexdigest()
    (args.output / "review.md").write_text(review_markdown(pool), encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "catalog_sha256": engine.manifest["catalog_sha256"],
        "vectors_sha256": engine.manifest["semantic"]["vectors_sha256"],
        "ranker_sha256": sha256(engine.path / "catboost_small.cbm"),
        "ensemble_config_sha256": sha256(engine.path / "ensemble_config.json"),
        "query_rule_sha256": sha256(Path("src/alfa_reco/query_rules.py")),
        "search_code_sha256": sha256(Path("src/alfa_reco/search.py")),
        "scenario_source_sha256": sha256(Path("src/alfa_reco/synthetic_scenarios.py")),
        "seed": args.seed,
        "queries": len(pool),
        "candidates": len(judgments),
        "hashes_before_review": hashes,
        "note": "No labels were generated. Blinded candidate pool from assistant-authored queries; not independent until external reviewers label it.",
    }
    with (args.output / "manifest.json").open("x", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
