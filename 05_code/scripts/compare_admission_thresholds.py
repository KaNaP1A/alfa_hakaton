"""Compare live search policies on the existing judged pool without changing model files."""

import argparse
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from alfa_reco.evaluation import metric_at_5, resolved_grade
from alfa_reco.search import SearchEngine


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def evaluate(pool_dir, judgments_file, catalog):
    manifest = json.loads((pool_dir / "manifest.json").read_text(encoding="utf-8"))
    for name in ("pool.jsonl", "rankings.jsonl"):
        if hashlib.sha256((pool_dir / name).read_bytes()).hexdigest() != manifest["hashes_before_review"][name]:
            raise ValueError("Frozen pool changed: " + name)
    pool, judgments = read_jsonl(pool_dir / "pool.jsonl"), read_jsonl(judgments_file)
    grades = {}
    for row in judgments:
        key = row["query_id"], row["entity_key"]
        if key in grades:
            raise ValueError("Duplicate judgment")
        grades[key] = resolved_grade(row)
    expected = {(q["query_id"], c["entity_key"]) for q in pool for c in q["candidates"]}
    if set(grades) != expected:
        raise ValueError("Judgments do not match frozen pool")
    eligible = [q for q in pool if all(grades[q["query_id"], c["entity_key"]] is not None
                                        for c in q["candidates"])]
    engine = SearchEngine(catalog, semantic=False, llm_enabled=False)
    if engine.manifest["catalog_sha256"] != manifest["catalog_sha256"]:
        raise ValueError("Catalog differs from the reviewed pool")
    backend = engine.relevance_backend()
    original_threshold = backend.policy["semantic_min"]
    if original_threshold != 0.84:
        raise ValueError("Baseline threshold differs from expected 0.84")
    summary, paired = defaultdict(Counter), defaultdict(list)
    changes = []
    try:
        for number, query in enumerate(eligible, 1):
            pool_grades = {c["entity_key"]: grades[query["query_id"], c["entity_key"]]
                           for c in query["candidates"]}
            orders = {}
            for name, threshold in (("baseline", original_threshold), ("proposed", 0.8)):
                backend.policy["semantic_min"] = threshold
                response = engine.search(query["query"], mode="relevance", top=5)
                order = [item["entity_key"] for item in response["results"]]
                orders[name] = order
                row = summary[(query["split"], name)]
                row["queries"] += 1
                row["empty"] += not bool(order)
                row["returned"] += len(order)
                row["unjudged"] += sum(key not in pool_grades for key in order)
                row["judged_irrelevant"] += sum(pool_grades.get(key) == 0 for key in order)
                row["judged_relevant_grade_2_or_3"] += sum(pool_grades.get(key) in (2, 3) for key in order)
            if orders["baseline"] != orders["proposed"]:
                changes.append({"query_id": query["query_id"], "split": query["split"],
                                "baseline": orders["baseline"], "proposed": orders["proposed"]})
            if all(set(order) <= set(pool_grades) for order in orders.values()):
                paired[query["split"]].append({
                    "family": query["family"],
                    **{name: metric_at_5(order, pool_grades) for name, order in orders.items()},
                })
            if number % 20 == 0:
                print(f"Checked {number}/{len(eligible)} questions", flush=True)
    finally:
        backend.policy["semantic_min"] = original_threshold
    reports = {}
    for split in sorted({key[0] for key in summary}):
        data = paired[split]
        groups = defaultdict(list)
        for row in data:
            groups[row["family"]].append(row)
        metric = {}
        for measure in ("ndcg5", "mrr5", "precision5"):
            metric[measure] = {}
            for name in ("baseline", "proposed"):
                means = []
                for group in groups.values():
                    values = [row[name][measure] for row in group if row[name][measure] is not None]
                    if values:
                        means.append(statistics.mean(values))
                metric[measure][name] = round(statistics.mean(means), 6) if means else None
        reports[split] = {"baseline": dict(summary[split, "baseline"]),
                          "proposed": dict(summary[split, "proposed"]),
                          "paired_queries": len(data), "paired_families": len(groups),
                          "paired_family_macro": metric}
    return {
        "generation": engine.generation,
        "thresholds": {"baseline": original_threshold, "proposed": 0.8},
        "complete_queries": len(eligible), "changed_queries": len(changes),
        "summary": reports, "changes": changes,
        "limitations": "Previously observed synthetic questions; incomplete candidate judgments. Unjudged outputs remain unjudged; paired metrics include only queries with both orders fully judged. Not an independent test.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--judgments", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=Path("artifacts/catalog"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Output already exists")
    result = evaluate(args.pool, args.judgments, args.catalog)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k != "changes"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
