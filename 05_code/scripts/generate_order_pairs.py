"""Generate a scoped robustness probe by moving one non-negated filler word."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from alfa_reco.cli import load_bundle
from alfa_reco.query_rules import ANY_NEGATION
from alfa_reco.synthetic import digest, normalize
from alfa_reco.text import tokens


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=150)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists")
    if not 1 <= args.limit <= 500:
        parser.error("Invalid limit")
    _, manifest, catalog = load_bundle("artifacts/catalog")
    buckets = defaultdict(list)
    seen = set()
    for item in catalog:
        title = " ".join(item["title"].split())
        key = normalize(title)
        if (
            not 2 <= len(tokens(title)) <= 7
            or len(title) > 130
            or not key
            or key in seen
            or ANY_NEGATION.search(title)
            or "хочу" in key.split()
            or any(mark in title for mark in ('"', "«", "»"))
        ):
            continue
        seen.add(key)
        buckets[item["kind"]].append(title)
    for titles in buckets.values():
        titles.sort(key=lambda title: digest(f"{args.seed}:{normalize(title)}"))
    chosen = []
    while buckets and len(chosen) < args.limit:
        for kind in sorted(list(buckets)):
            if len(chosen) >= args.limit:
                break
            chosen.append(buckets[kind].pop())
            if not buckets[kind]:
                del buckets[kind]
    result = {
        "catalog_sha256": manifest["catalog_sha256"],
        "seed": args.seed,
        "description": "Только перестановка вводного слова хочу; заголовки из каталога. Не является проверкой произвольного порядка и не содержит оценок релевантности.",
        "pairs": [[f"хочу {title}", f"{title} хочу"] for title in chosen],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print("pairs:", len(chosen))


if __name__ == "__main__":
    main()
