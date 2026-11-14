"""Check profile ranking against existing judged pools; unknown items stay unknown."""

import argparse
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from alfa_reco.evaluation import metric_at_5, resolved_grade
from alfa_reco.profile import recommend_for_profile
from alfa_reco.search import SearchEngine

SCENARIOS = {
    "goal_only": {},
    "preferred_course": {"preferred_kinds": ["course"]},
    "retail": {"industry": "ритейл"},
    "beginner": {"experience": "beginner"},
    "launch": {"business_stage": "launch"},
    "combined": {"preferred_kinds": ["course"], "industry": "ритейл", "experience": "beginner", "business_stage": "launch"},
}


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def family_mean(rows, field, metric):
    groups = defaultdict(list)
    for row in rows:
        value = row[field][metric]
        if value is not None:
            groups[row["family"]].append(value)
    return round(statistics.mean(statistics.mean(values) for values in groups.values()), 6) if groups else None


def evaluate(directory, judgments_path, output, split="all"):
    if output.exists():
        raise ValueError("Output already exists")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    for name in ("pool.jsonl", "rankings.jsonl"):
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != manifest["hashes_before_review"][name]:
            raise ValueError(f"Frozen input changed: {name}")
    pool = read_jsonl(directory / "pool.jsonl")
    rankings = {row["query_id"]: row["rankings"]["relevance"] for row in read_jsonl(directory / "rankings.jsonl")}
    judgments = read_jsonl(judgments_path)
    grades = {}
    for row in judgments:
        key = row["query_id"], row["entity_key"]
        if key in grades:
            raise ValueError("Duplicate judgment")
        grades[key] = resolved_grade(row)
    expected = {(q["query_id"], c["entity_key"]) for q in pool for c in q["candidates"]}
    if set(grades) != expected or set(rankings) != {q["query_id"] for q in pool}:
        raise ValueError("Evaluation inputs do not match")
    engine = SearchEngine("artifacts/catalog", semantic=False, llm_enabled=False)
    if engine.manifest["catalog_sha256"] != manifest["catalog_sha256"]:
        raise ValueError("Catalog differs from frozen pool")
    eligible = [q for q in pool if (split == "all" or q["split"] == split)
                and all(grades[q["query_id"], c["entity_key"]] is not None for c in q["candidates"])]
    stats, paired = defaultdict(Counter), defaultdict(list)
    baseline_changed = 0

    class CachedSearch:
        generation = engine.generation
        catalog = engine.catalog

        def search(self, query, *, mode, top):
            if query != current_query or mode != "relevance" or top != 50:
                raise ValueError("Unexpected diagnostic search")
            return current_search

    cached = CachedSearch()
    for number, query in enumerate(eligible, 1):
        current_query = query["query"]
        current_search = engine.search(current_query, mode="relevance", top=50)
        original = rankings[query["query_id"]][:5]
        pool_grades = {c["entity_key"]: grades[query["query_id"], c["entity_key"]] for c in query["candidates"]}
        if not set(original) <= set(pool_grades):
            raise ValueError("Frozen ranking contains unknown candidates")
        baseline_metrics = metric_at_5(original, pool_grades)
        for name, preferences in SCENARIOS.items():
            profile = {"generation": engine.generation, "goal": current_query, **preferences}
            response = recommend_for_profile(cached, profile, limit=5)
            order = [item["entity_key"] for item in response["results"]]
            row = stats[(query["split"], name)]
            row["completed_queries"] += 1
            row["changed_order"] += order != original
            row["empty"] += not bool(order)
            row["uncertain_with_results"] += response["status"] == "uncertain"
            unknown = sum(key not in pool_grades for key in order)
            row["returned"] += len(order)
            row["unjudged_returned"] += unknown
            if not unknown:
                paired[(query["split"], name)].append({
                    "family": query["family"], "baseline": baseline_metrics,
                    "profile": metric_at_5(order, pool_grades),
                })
            if name == "goal_only" and order != original:
                baseline_changed += 1
        if number % 20 == 0:
            print(f"Checked {number}/{len(eligible)} queries", flush=True)
    summary = {}
    for (group, name), values in sorted(stats.items()):
        samples = paired[(group, name)]
        summary.setdefault(group, {})[name] = {
            **values,
            "paired_queries": len(samples),
            "paired_families": len({row["family"] for row in samples}),
            "paired_family_macro": {
                metric: {field: family_mean(samples, field, metric) for field in ("baseline", "profile")}
                for metric in ("precision5", "mrr5", "ndcg5")
            },
        }
    result = {
        "generation": engine.generation,
        "complete_queries": len(eligible),
        "baseline_goal_only_changed": baseline_changed,
        "scenarios": SCENARIOS,
        "summary": summary,
        "limitations": "Synthetic profiles on already-seen questions. Labels measure query relevance only, not profile fit. Paired metrics exclude any result outside the judged pool and may be biased; NDCG ideal is restricted to this pool. No new human judgments or independent test.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--judgments", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("all", "train", "validation"), default="all")
    args = parser.parse_args()
    report = evaluate(args.pool, args.judgments, args.output, args.split)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
