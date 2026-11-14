"""Apply manually adjudicated grades to a copied merged review, never guessing blanks."""

import argparse
import hashlib
import json
from pathlib import Path

from alfa_reco.evaluation import resolved_grade

if __package__:
    from scripts.import_review_csv import xlsx_rows
else:
    from import_review_csv import xlsx_rows


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def import_adjudications(directory, merged_path, workbook, output):
    if output.exists():
        raise ValueError("Output already exists")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    for name in ("pool.jsonl", "rankings.jsonl"):
        if (
            hashlib.sha256((directory / name).read_bytes()).hexdigest()
            != manifest["hashes_before_review"][name]
        ):
            raise ValueError(f"Frozen evaluation file changed: {name}")
    pool = read_jsonl(directory / "pool.jsonl")
    expected = {(q["query_id"], c["entity_key"]): (q, c) for q in pool for c in q["candidates"]}
    merged = read_jsonl(merged_path)
    rows = {(r["query_id"], r["entity_key"]): r for r in merged}
    if len(rows) != len(merged) or set(rows) != set(expected):
        raise ValueError("Merged reviews do not match the original pool")
    for row in merged:
        resolved_grade(row)
        if row.get("adjudicated") is not None:
            raise ValueError("Expected the original, non-adjudicated merge")
    pending = {
        key
        for key, r in rows.items()
        if r.get("reviewer_a") is None
        or r.get("reviewer_b") is None
        or r["reviewer_a"] != r["reviewer_b"]
    }
    seen = set()
    for row in xlsx_rows(workbook):
        key = (row.get("query_id"), row.get("entity_key"))
        if key in seen or key not in pending:
            raise ValueError("Duplicate or unknown pending candidate")
        seen.add(key)
        initial = rows[key]
        for reviewer in ("reviewer_a", "reviewer_b"):
            expected_value = "" if initial.get(reviewer) is None else str(initial[reviewer])
            if row.get(reviewer, "") != expected_value:
                raise ValueError("Original reviewer grades must not be changed")
        q, c = expected[key]

        def safe(value):
            return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value

        if any(
            row.get(field, "") != safe(value)
            for field, value in (
                ("query", q["query"]),
                ("title", c["title"]),
                ("description", c["description"]),
            )
        ):
            raise ValueError("Query or candidate text was modified")
        grade = row.get("adjudicated", "").strip()
        if grade not in {"", "0", "1", "2", "3"}:
            raise ValueError("Adjudication must be blank or an integer 0–3")
        initial["adjudicated"] = int(grade) if grade else None
    if seen != pending:
        raise ValueError("Workbook must include every unresolved candidate")
    with output.open("x", encoding="utf-8") as stream:
        for row in merged:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    completed = sum(r["adjudicated"] is not None for r in merged)
    return completed, len(pending) - completed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("merged", type=Path)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    completed, pending = import_adjudications(
        args.directory, args.merged, args.workbook, args.output
    )
    print(f"Imported {completed} adjudications; {pending} remain unresolved.")


if __name__ == "__main__":
    main()
