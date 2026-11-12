"""Combine two independent reviewers' JSONL files without guessing disagreements."""

import argparse
import json
from pathlib import Path

from alfa_reco.evaluation import resolved_grade


def index_rows(rows, reviewer):
    output = {}
    other = "reviewer_b" if reviewer == "reviewer_a" else "reviewer_a"
    for row in rows:
        key = (row["query_id"], row["entity_key"])
        if key in output:
            raise ValueError("Duplicate judgment")
        if row.get(other) is not None or row.get("adjudicated") is not None:
            raise ValueError("Each independent review must fill only its own column")
        value = row.get(reviewer)
        resolved_grade(row)
        output[key] = value
    return output


def merge(first, second):
    a = index_rows(first, "reviewer_a")
    b = index_rows(second, "reviewer_b")
    if set(a) != set(b):
        raise ValueError("Reviewer files do not cover the same candidate pairs")
    return [
        {
            "query_id": qid,
            "entity_key": key,
            "reviewer_a": a[(qid, key)],
            "reviewer_b": b[(qid, key)],
            "adjudicated": None,
        }
        for qid, key in sorted(a)
    ]


def read(path):
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reviewer_a", type=Path)
    parser.add_argument("reviewer_b", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = merge(read(args.reviewer_a), read(args.reviewer_b))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"Merged {len(rows)} judgments; disagreements require adjudication.")


if __name__ == "__main__":
    main()
