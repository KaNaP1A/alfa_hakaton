"""Diagnostic pooled metrics for automatic drafts; never substitutes human judgments."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from audit_ranking import family_average, pooled_metrics

from alfa_reco.bundle import atomic_json, sha256


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, default=Path("artifacts/annotation_pool/relevance_v1"))
    parser.add_argument("--drafts", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((args.pool / "manifest.json").read_text())
    for name in ("pool.jsonl", "rankings.jsonl"):
        if sha256(args.pool / name) != manifest["hashes_before_review"][name]:
            raise ValueError(f"Frozen pool changed: {name}")
    queries = read_rows(args.pool / "pool.jsonl")
    rankings = {r["query_id"]: r["rankings"] for r in read_rows(args.pool / "rankings.jsonl")}
    # Append-only retries replace earlier attempts; unknown grades stay unknown.
    drafts = {(r["query_id"], r["entity_key"]): r for r in read_rows(args.drafts / "ratings.jsonl")}
    grouped = defaultdict(lambda: defaultdict(list))
    complete, missing = [], []
    expected = {(q["query_id"], c["entity_key"]) for q in queries for c in q["candidates"]}
    if drafts.keys() - expected:
        raise ValueError("Draft assessment contains a foreign query or document")
    for q in queries:
        grades = {}
        for card in q["candidates"]:
            r = drafts.get((q["query_id"], card["entity_key"]), {})
            grade = r.get("grade")
            if type(grade) is int and 0 <= grade <= 3 and r.get("human_verified") is False:
                grades[card["entity_key"]] = grade
        if len(grades) != len(q["candidates"]):
            missing.append(q["query_id"])
            continue
        complete.append(q["query_id"])
        for method, order in rankings[q["query_id"]].items():
            if set(order) - grades.keys():
                raise ValueError("A ranked result is outside its assessed pool")
            grouped[q["split"]][method].append(
                {"family": q["family"], "metrics": pooled_metrics(order, grades)}
            )
    report = {
        "assessment_source": "local_model_draft_not_human_gold",
        "expected_pairs": len(expected),
        "assessed_pairs": len(drafts),
        "graded_pairs": sum(type(r.get("grade")) is int for r in drafts.values()),
        "queries": len(queries),
        "fully_graded_queries": len(complete),
        "excluded_incomplete_queries": missing,
        "models_by_pair": dict(Counter(r["model"] for r in drafts.values())),
        "quality": {
            split: {method: family_average(rows) for method, rows in methods.items()}
            for split, methods in grouped.items()
        },
        "hashes": {
            "pool": sha256(args.pool / "pool.jsonl"),
            "rankings": sha256(args.pool / "rankings.jsonl"),
            "ratings": sha256(args.drafts / "ratings.jsonl"),
        },
        "limits": (
            "Automatic diagnostic only. No human agreement or reliability established. "
            "Historical baseline snapshots can differ from current serving policies. "
            "NDCG ideal is computed over each entire pooled candidate set, not the full catalog. "
            "These numbers cannot be compared directly with earlier four-judgment NDCG. "
            "No training or threshold selection uses these draft labels."
        ),
    }
    atomic_json(args.drafts / "metrics.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
