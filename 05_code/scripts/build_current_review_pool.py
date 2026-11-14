"""Freeze current search outputs for independent review of an already-seen diagnostic set.

The queries are historical, so this is not an unseen test. No labels are generated.
"""

import argparse
import csv
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path

from alfa_reco.bundle import sha256
from alfa_reco.eligibility import USER_KINDS
from alfa_reco.search import SearchEngine


def jsonl(rows):
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)


def build(source, output, seed=20261112):
    if output.exists():
        raise ValueError("Output already exists")
    cases = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line]
    if not cases or len({x["query_id"] for x in cases}) != len(cases):
        raise ValueError("Empty or duplicate cases")
    engine = SearchEngine("artifacts/catalog", semantic=False, llm_enabled=False)
    backend = engine.relevance_backend()
    ranker = backend.model
    if ranker is None:
        raise ValueError("Relevance ranker is not loaded")
    catalog = [item for item in engine.catalog if item["kind"] in USER_KINDS]
    pool, rankings, judgments, diagnostics = [], [], [], []
    for number, case in enumerate(cases, 1):
        qid = case["query_id"]
        query = case["query"]
        candidates, orders = {}, {}
        try:
            for method in ("e5_without_ranker", "relevance"):
                backend.model = None if method == "e5_without_ranker" else ranker
                result = engine.search(query, mode="relevance", top=5)
                orders[method] = [item["entity_key"] for item in result["results"]]
                for item in result["results"] + result["alternatives"]:
                    candidates[item["entity_key"]] = {
                        k: item[k] for k in ("entity_key", "title", "description", "kind")
                    }
        finally:
            backend.model = ranker
        # Random catalog items widen the blind pool; they are not negative labels.
        rng = random.Random(int(hashlib.sha256(f"{seed}:{qid}".encode()).hexdigest(), 16))
        sample = rng.sample(catalog, min(3, len(catalog)))
        for item in sample:
            candidates[item["entity_key"]] = {
                k: item[k] for k in ("entity_key", "title", "description", "kind")
            }
        ordered = sorted(
            candidates.values(),
            key=lambda item: hashlib.sha256(
                f"{seed}:{qid}:{item['entity_key']}".encode()
            ).hexdigest(),
        )
        pool.append(
            {
                "query_id": qid,
                "family": case["family"],
                "split": "validation",
                "query": query,
                "candidates": ordered,
            }
        )
        rankings.append({"query_id": qid, "rankings": orders})
        judgments.extend(
            {
                "query_id": qid,
                "entity_key": item["entity_key"],
                "reviewer_a": None,
                "reviewer_b": None,
                "adjudicated": None,
            }
            for item in ordered
        )
        diagnostics.append(
            {
                "query_id": qid,
                "returned": {k: len(v) for k, v in orders.items()},
                "pool_size": len(ordered),
            }
        )
        if number % 15 == 0:
            print(f"Prepared {number}/{len(cases)}", flush=True)
    output.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name, rows in (
        ("pool.jsonl", pool),
        ("rankings.jsonl", rankings),
        ("judgments.jsonl", judgments),
        ("diagnostics.jsonl", diagnostics),
    ):
        path = output / name
        path.write_text(jsonl(rows), encoding="utf-8")
        hashes[name] = sha256(path)
    for reviewer in ("reviewer_a", "reviewer_b"):
        directory = output / reviewer
        directory.mkdir()
        with (directory / "review.csv").open("x", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(
                ["query_id", "query", "entity_key", "kind", "title", "description", "grade"]
            )
            for row in pool:
                for item in row["candidates"]:
                    fields = [
                        row["query_id"],
                        row["query"],
                        item["entity_key"],
                        item["kind"],
                        item["title"],
                        item["description"],
                    ]
                    # Avoid spreadsheet formula interpretation of catalog-controlled text.
                    fields = [
                        "'" + x if str(x).lstrip().startswith(("=", "+", "-", "@")) else x
                        for x in fields
                    ]
                    writer.writerow([*fields, ""])
    manifest = {
        "schema_version": 1,
        "purpose": "historical_diagnostic_not_blind_holdout",
        "catalog_generation": engine.generation,
        "catalog_sha256": engine.manifest["catalog_sha256"],
        "model_manifest_sha256": sha256(backend.path / "manifest.json"),
        "source_queries_sha256": sha256(source),
        "builder_sha256": sha256(Path(__file__)),
        "code_hashes": {p.name: sha256(p) for p in sorted(Path("src/alfa_reco").glob("*.py"))},
        "python": sys.version.split()[0],
        "seed": seed,
        "queries": len(pool),
        "families": len({x["family"] for x in pool}),
        "candidates": len(judgments),
        "returned": {
            name: dict(Counter(len(x["rankings"][name]) for x in rankings))
            for name in ("e5_without_ranker", "relevance")
        },
        "hashes_before_review": hashes,
        "note": "Old assistant-authored queries; all validation for diagnostics only. E5 baseline is current relevance pipeline with ranker disabled. All candidates are unlabeled; no claim of no-answer or human quality.",
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=Path("evaluation/challenge_v2/real_pool_pool.jsonl")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261112)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output, args.seed), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
