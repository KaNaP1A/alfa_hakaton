"""Strict evaluation of a blinded, human-judged candidate pool."""

import math
from collections import defaultdict


def resolved_grade(row):
    """Resolve two ratings; a disagreement requires an adjudicated grade."""
    if row.get("automatic_hint_seen") or row.get("human_verified") is False:
        raise ValueError("Automatic or assisted ratings cannot be used as blinded human judgments")
    if row.get("assessor") == "local_model_draft":
        raise ValueError("Automatic drafts cannot be used as human judgments")
    values = [row.get(name) for name in ("reviewer_a", "reviewer_b", "adjudicated")]
    if any(
        value is not None and (type(value) is not int or not 0 <= value <= 3) for value in values
    ):
        raise ValueError("Grades must be null or integers from 0 to 3")
    first, second, final = values
    if final is not None:
        return final
    if first is not None and first == second:
        return first
    return None


def metric_at_5(order, grades):
    values = [grades[key] for key in order[:5]]
    precision = sum(value >= 2 for value in values) / 5
    mrr = next((1 / index for index, value in enumerate(values, 1) if value >= 2), 0.0)

    def dcg(seq):
        return sum((2**grade - 1) / math.log2(i + 2) for i, grade in enumerate(seq))

    ideal = dcg(sorted(grades.values(), reverse=True)[:5])
    return {"precision5": precision, "mrr5": mrr, "ndcg5": dcg(values) / ideal if ideal else None}


def evaluate_pool(pool, rankings, judgments):
    queries = {row["query_id"]: row for row in pool}
    ranks = {row["query_id"]: row for row in rankings}
    if len(queries) != len(pool) or len(ranks) != len(rankings) or set(queries) != set(ranks):
        raise ValueError("Duplicate or inconsistent query IDs")
    grade_map = {}
    disagreements = 0
    for row in judgments:
        key = (row["query_id"], row["entity_key"])
        if key in grade_map:
            raise ValueError("Duplicate candidate judgment")
        grade_map[key] = resolved_grade(row)
        if (
            row.get("reviewer_a") is not None
            and row.get("reviewer_b") is not None
            and row["reviewer_a"] != row["reviewer_b"]
            and row.get("adjudicated") is None
        ):
            disagreements += 1
    groups = defaultdict(set)
    expected = set()
    for qid, query in queries.items():
        if query["split"] not in ("train", "validation", "test"):
            raise ValueError("Invalid split")
        groups[query["family"]].add(query["split"])
        ids = [item["entity_key"] for item in query["candidates"]]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate candidate")
        expected.update((qid, key) for key in ids)
        for order in ranks[qid]["rankings"].values():
            if len(set(order)) != len(order) or not set(order) <= set(ids):
                raise ValueError("Invalid ranked candidate")
    if any(len(values) > 1 for values in groups.values()):
        raise ValueError("Query family crosses splits")
    if set(grade_map) != expected:
        raise ValueError("Judgment rows must match the entire pool exactly")
    per_split = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    complete = 0
    for qid, query in queries.items():
        grades = {
            candidate["entity_key"]: grade_map[(qid, candidate["entity_key"])]
            for candidate in query["candidates"]
        }
        if not grades or any(value is None for value in grades.values()):
            continue
        complete += 1
        for method, order in ranks[qid]["rankings"].items():
            per_split[query["split"]][method][query["family"]].append(metric_at_5(order, grades))
    summary = {}
    for split, methods in sorted(per_split.items()):
        summary[split] = {}
        for method, families in sorted(methods.items()):
            values = {}
            for metric in ("precision5", "mrr5", "ndcg5"):
                family_means = []
                for rows in families.values():
                    numeric = [row[metric] for row in rows if row[metric] is not None]
                    if numeric:
                        family_means.append(sum(numeric) / len(numeric))
                values[metric] = (
                    round(sum(family_means) / len(family_means), 6) if family_means else None
                )
            summary[split][method] = values
    return {
        "queries": len(queries),
        "completed_queries": complete,
        "pending_queries": len(queries) - complete,
        "candidate_judgments": len(grade_map),
        "resolved_judgments": sum(v is not None for v in grade_map.values()),
        "unresolved_disagreements": disagreements,
        "metrics_by_split_and_method": summary,
        "limitations": "Metrics include only fully judged pools; NDCG ideal is restricted to pooled candidates. Unjudged cases are excluded, not treated as zero. A pool cannot establish absence in the whole catalog.",
    }
