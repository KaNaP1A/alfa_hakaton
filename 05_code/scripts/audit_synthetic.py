"""Independent structural audit for a synthetic query dataset, not a relevance evaluator."""

import argparse
import hashlib
import itertools
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from alfa_reco.cli import load_bundle

SPLITS = {"train", "validation", "test"}
TASKS = {"search", "autocomplete"}
STATUS = {"weak_source_reference", "unjudged"}


def normalize(text):
    """Independent exact-match key; no claim of detecting semantic paraphrases."""
    text = unicodedata.normalize("NFKC", str(text)).casefold().replace("ё", "е")
    return " ".join(re.findall(r"[^\W_]+|[+#]+", text, re.UNICODE))


def protected_from_files(paths):
    ids, titles, queries = set(), set(), set()
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for row in data["queries"]:
            queries.add(normalize(row["query"]))
            for judgment in row["judgments"]:
                ids.add(judgment["entity_key"])
                if judgment.get("title"):
                    titles.add(normalize(judgment["title"]))
    return ids, titles, queries


def near_duplicate_title_risks(references):
    """Find high lexical overlap among referenced titles in different splits.

    This is a warning, not proof of semantic leakage or of independence. Very
    common terms are skipped to bound the inverted index's pair count.
    """
    data = []
    for source_id, (title, split) in sorted(references.items()):
        terms = set(normalize(title).split())
        if len(terms) >= 3:
            data.append((source_id, title, split, terms))
    postings = defaultdict(list)
    for i, (_, _, _, terms) in enumerate(data):
        for term in terms:
            postings[term].append(i)
    shared = Counter()
    ignored = sum(len(indices) > 200 for indices in postings.values())
    for indices in postings.values():
        if len(indices) > 200:
            continue
        for a, b in itertools.combinations(indices, 2):
            if data[a][2] != data[b][2]:
                shared[(a, b)] += 1
    risks = []
    for (a, b), overlap in shared.items():
        if overlap < 3:
            continue
        jaccard = len(data[a][3] & data[b][3]) / len(data[a][3] | data[b][3])
        if jaccard >= 0.8:
            risks.append(
                {
                    "left_id": data[a][0],
                    "left_title": data[a][1],
                    "left_split": data[a][2],
                    "right_id": data[b][0],
                    "right_title": data[b][1],
                    "right_split": data[b][2],
                    "jaccard": round(jaccard, 4),
                }
            )
    risks.sort(key=lambda x: (-x["jaccard"], x["left_id"], x["right_id"]))
    return {
        "count": len(risks),
        "examples": risks[:25],
        "ignored_frequent_terms": ignored,
        "note": "Lexical title similarity only; incomplete search, not a semantic guarantee.",
    }


def review_sample(rows, limit=120):
    """Deterministic round-robin sample across scenario, split and material kind."""
    buckets = defaultdict(list)
    for row in rows:
        key = (row.get("scenario"), row.get("split"), row.get("kind") or "none")
        buckets[key].append(row)
    for bucket in buckets.values():
        bucket.sort(key=lambda row: hashlib.sha256(row["query_id"].encode()).digest())
    selected = []
    while len(selected) < limit and buckets:
        for key in sorted(list(buckets)):
            if len(selected) >= limit:
                break
            row = buckets[key].pop()
            selected.append(
                {
                    "query_id": row["query_id"],
                    "query": row["query"],
                    "split": row["split"],
                    "scenario": row["scenario"],
                    "kind": row.get("kind"),
                    "source_id": row.get("source_id"),
                    "label_status": row.get("label_status"),
                    "judgment": None,
                }
            )
            if not buckets[key]:
                del buckets[key]
    return selected


def audit_rows(rows, catalog, protected_ids=(), protected_titles=(), protected_queries=()):
    lookup = {item["entity_key"]: item for item in catalog}
    protected_ids, protected_titles, protected_queries = (
        set(protected_ids),
        set(protected_titles),
        set(protected_queries),
    )
    protected_titles.update(
        normalize(item.get("title", "")) for item in catalog if item["entity_key"] in protected_ids
    )
    required = {
        "query_id",
        "query",
        "split",
        "group_id",
        "scenario",
        "task",
        "source_id",
        "kind",
        "label_status",
        "relevance",
    }
    errors = Counter()
    examples = defaultdict(list)
    ids, query_splits, group_splits, source_splits = (
        defaultdict(set),
        defaultdict(set),
        defaultdict(set),
        defaultdict(set),
    )
    query_counts = Counter()
    counts = {name: Counter() for name in ("split", "task", "scenario", "kind", "label_status")}
    catalog_kinds = Counter(item["kind"] for item in catalog)
    observed_sources = set()
    references = {}
    usable = []

    def fail(name, detail):
        errors[name] += 1
        if len(examples[name]) < 10:
            examples[name].append(detail)

    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            fail("invalid_schema", f"line {index}: non-object")
            continue
        missing = required - row.keys()
        if missing:
            fail("invalid_schema", f"line {index}: missing {sorted(missing)}")
            continue
        qid, query, group = row["query_id"], row["query"], row["group_id"]
        if not all(isinstance(value, str) and value for value in (qid, query, group)):
            fail("invalid_schema", f"line {index}: invalid query_id/query/group_id")
            continue
        if len(query.strip()) < 2 or len(query) > 300 or not normalize(query):
            fail("invalid_query_length_or_text", qid)
        split, task, status = row["split"], row["task"], row["label_status"]
        if split not in SPLITS or task not in TASKS or status not in STATUS:
            fail("invalid_metadata", qid)
        if row["relevance"] is not None:
            fail("unverified_relevance_as_truth", qid)
        if status == "weak_source_reference" and not row["source_id"]:
            fail("weak_reference_without_source", qid)
        if status == "unjudged" and row["source_id"] is not None:
            fail("unjudged_has_source", qid)
        for name in counts:
            counts[name][str(row[name])] += 1
        key = normalize(query)
        ids[qid].add(index)
        query_splits[key].add(split)
        query_counts[key] += 1
        group_splits[group].add(split)
        if key in protected_queries:
            fail("protected_query_overlap", qid)
        source_id = row["source_id"]
        if source_id is not None:
            source_splits[source_id].add(split)
            observed_sources.add(source_id)
            item = lookup.get(source_id)
            if not item:
                fail("unknown_source_id", qid)
            else:
                if item.get("kind") != row["kind"]:
                    fail("source_kind_mismatch", qid)
                title = item.get("title", "")
                references[source_id] = (title, split)
                if normalize(title) in protected_titles:
                    fail("protected_title_overlap", qid)
            if source_id in protected_ids:
                fail("protected_source_overlap", qid)
        usable.append(row)

    for key, value in ids.items():
        if len(value) > 1:
            fail("duplicate_query_id", key)
    for key, count in query_counts.items():
        if count > 1:
            fail("duplicate_normalized_query", key)
    for key, splits in query_splits.items():
        if len(splits) > 1:
            fail("query_cross_split", key)
    for key, splits in group_splits.items():
        if len(splits) > 1:
            fail("group_cross_split", key)
    for key, splits in source_splits.items():
        if len(splits) > 1:
            fail("source_cross_split", key)
    title_splits = defaultdict(set)
    for title, split in references.values():
        title_splits[normalize(title)].add(split)
    for key, splits in title_splits.items():
        if len(splits) > 1:
            fail("normalized_title_cross_split", key)

    covered_kinds = Counter(lookup[key]["kind"] for key in observed_sources if key in lookup)
    return {
        "passed_structural_checks": not bool(errors),
        "errors": dict(sorted(errors.items())),
        "error_examples": dict(sorted(examples.items())),
        "row_count": len(rows),
        "unique_normalized_queries": len(query_counts),
        "unique_groups": len(group_splits),
        "unique_sources": len(observed_sources),
        "counts": {key: dict(sorted(value.items())) for key, value in counts.items()},
        "catalog_counts_by_kind": dict(sorted(catalog_kinds.items())),
        "covered_source_counts_by_kind": dict(sorted(covered_kinds.items())),
        "near_duplicate_titles_cross_split": near_duplicate_title_risks(references),
        "review_sample": review_sample(usable),
        "limitations": [
            "A source reference is a weak provenance link, not a relevance judgment.",
            "Unknown results are not negative labels; manual review is still required.",
            "Exact/group checks and title similarity cannot prove semantic independence.",
            "Synthetic catalog-derived queries are not real user search traffic.",
        ],
    }


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="Directory containing queries.jsonl")
    parser.add_argument("--catalog", default="artifacts/catalog")
    parser.add_argument(
        "--compare", type=Path, help="Another generated directory for reproducibility"
    )
    parser.add_argument(
        "--output", type=Path, help="Write audit JSON to a new file (never overwrite)"
    )
    args = parser.parse_args()
    dataset_file = args.dataset / "queries.jsonl"
    rows = read_jsonl(dataset_file)
    _, catalog_manifest, catalog = load_bundle(args.catalog)
    protected = protected_from_files(
        ["evaluation/ensemble_cases_v2.json", "evaluation/judgments.json"]
    )
    report = audit_rows(rows, catalog, *protected)
    report["queries_sha256"] = hashlib.sha256(dataset_file.read_bytes()).hexdigest()
    manifest_file = args.dataset / "manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("queries_sha256") != report["queries_sha256"]:
        report["passed_structural_checks"] = False
        report["errors"]["query_hash_mismatch"] = 1
    review_hash = hashlib.sha256((args.dataset / "review.jsonl").read_bytes()).hexdigest()
    review_md_hash = hashlib.sha256((args.dataset / "review.md").read_bytes()).hexdigest()
    report["review_unchanged"] = {
        "jsonl": manifest.get("review_sha256") == review_hash,
        "markdown": manifest.get("review_markdown_sha256") == review_md_hash,
        "note": "Review files are intended to be edited; changed hashes are informational.",
    }
    report["catalog_fingerprint_matches"] = manifest.get("catalog_sha256") == catalog_manifest.get(
        "catalog_sha256"
    )
    if not report["catalog_fingerprint_matches"]:
        report["passed_structural_checks"] = False
        report["errors"]["catalog_fingerprint_mismatch"] = 1
    expected_protected_hashes = {
        name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
        for name in ("evaluation/ensemble_cases_v2.json", "evaluation/judgments.json")
    }
    if manifest.get("protected_files") != expected_protected_hashes:
        report["passed_structural_checks"] = False
        report["errors"]["protected_file_hash_mismatch"] = 1
    generator_hashes = {
        name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
        for name in (
            "src/alfa_reco/synthetic.py",
            "src/alfa_reco/synthetic_scenarios.py",
            "scripts/generate_synthetic.py",
        )
    }
    report["generator_code_matches"] = manifest.get("generator_files") == generator_hashes
    if args.compare:
        other_file = args.compare / "queries.jsonl"
        other_hash = hashlib.sha256(other_file.read_bytes()).hexdigest()
        report["reproducibility"] = {
            "queries_sha256_equal": report["queries_sha256"] == other_hash,
            "other_queries_sha256": other_hash,
        }
        if not report["reproducibility"]["queries_sha256_equal"]:
            report["passed_structural_checks"] = False
            report["errors"]["reproducibility_mismatch"] = 1
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(serialized)
    else:
        print(serialized, end="")
    if not report["passed_structural_checks"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
