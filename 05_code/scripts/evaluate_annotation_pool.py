"""Evaluate only independently reviewed, fully judged candidate pools."""

import argparse
import hashlib
import json
from pathlib import Path

from alfa_reco.evaluation import evaluate_pool


def read_rows(path):
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--judgments", type=Path, help="Reviewed JSONL, defaults to judgments.jsonl"
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists")
    manifest = json.loads((args.directory / "manifest.json").read_text(encoding="utf-8"))
    for name in ("pool.jsonl", "rankings.jsonl"):
        actual = hashlib.sha256((args.directory / name).read_bytes()).hexdigest()
        if actual != manifest["hashes_before_review"][name]:
            raise ValueError(f"Immutable evaluation file changed: {name}")
    report = evaluate_pool(
        read_rows(args.directory / "pool.jsonl"),
        read_rows(args.directory / "rankings.jsonl"),
        read_rows(args.judgments or args.directory / "judgments.jsonl"),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
