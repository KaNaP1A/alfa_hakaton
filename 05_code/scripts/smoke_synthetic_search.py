"""Measure source-card hit on a stratified synthetic sample; this is not relevance quality."""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from alfa_reco.search import SearchEngine


def choose_sample(rows, size, seed):
    buckets = defaultdict(list)
    for row in rows:
        if row["task"] == "search" and row["source_id"]:
            buckets[row["scenario"]].append(row)
    for bucket in buckets.values():
        bucket.sort(
            key=lambda row: hashlib.sha256(f"{seed}:{row['query_id']}".encode()).hexdigest()
        )
    chosen = []
    while buckets and len(chosen) < size:
        for key in sorted(list(buckets)):
            if len(chosen) >= size:
                break
            chosen.append(buckets[key].pop())
            if not buckets[key]:
                del buckets[key]
    return chosen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New JSON file")
    parser.add_argument("--size", type=int, default=90)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--catalog", default="artifacts/catalog")
    args = parser.parse_args()
    if not 1 <= args.size <= 5000:
        parser.error("size must be between 1 and 5000")
    if args.output.exists():
        parser.error("Output already exists")
    with (args.dataset / "queries.jsonl").open(encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    manifest = json.loads((args.dataset / "manifest.json").read_text(encoding="utf-8"))
    actual_hash = hashlib.sha256((args.dataset / "queries.jsonl").read_bytes()).hexdigest()
    if manifest["queries_sha256"] != actual_hash:
        raise ValueError("Dataset hash mismatch")
    engine = SearchEngine(args.catalog, semantic=True, llm_enabled=False)
    if manifest["catalog_sha256"] != engine.manifest["catalog_sha256"]:
        raise ValueError("Dataset belongs to a different catalog")
    sample = choose_sample(rows, args.size, args.seed)
    if not sample:
        raise ValueError("No search probes with source reference")
    evaluated = []
    for index, row in enumerate(sample):
        result = engine.search(row["query"], top=5, mode="ensemble")
        top = [item["entity_key"] for item in result["results"]]
        evaluated.append(
            {
                "query_id": row["query_id"],
                "query": row["query"],
                "scenario": row["scenario"],
                "source_id": row["source_id"],
                "source_in_top5": row["source_id"] in top,
                "top5": [{"id": x["entity_key"], "title": x["title"]} for x in result["results"]],
            }
        )
        if (index + 1) % 20 == 0:
            print(f"{index + 1}/{len(sample)}", flush=True)
    counts = Counter(row["scenario"] for row in evaluated)
    hits = Counter(row["scenario"] for row in evaluated if row["source_in_top5"])
    report = {
        "dataset_sha256": actual_hash,
        "catalog_sha256": manifest["catalog_sha256"],
        "sample_seed": args.seed,
        "sample_size": len(sample),
        "source_hit_at_5": round(sum(hits.values()) / len(sample), 4),
        "by_scenario": {
            name: {
                "queries": count,
                "hits": hits[name],
                "source_hit_at_5": round(hits[name] / count, 4),
            }
            for name, count in sorted(counts.items())
        },
        "caveat": "Exact source-card hits on catalog-derived synthetic queries, not precision, recall of relevant items, semantic validity, or real-user performance. Sample is intentionally balanced, not representative.",
        "results": evaluated,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "results"}, ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
