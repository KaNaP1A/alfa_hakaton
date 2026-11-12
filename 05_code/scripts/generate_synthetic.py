"""Generate an isolated, reproducible catalog-based query probe dataset."""

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from alfa_reco.cli import load_bundle
from alfa_reco.synthetic import VERSION, build_dataset, protected_from_files, review_sample

PROTECTED = [Path("evaluation/ensemble_cases_v2.json"), Path("evaluation/judgments.json")]


def jsonl(rows):
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)


def review_markdown(rows):
    def escape(value):
        value = str(value).replace("<", "&lt;").replace(">", "&gt;")
        return re.sub(r"([\\`*_{}\[\]()#!|])", r"\\\1", value)

    lines = [
        "# Проверка синтетических запросов",
        "",
        "Выборка автоматическая. Исходная карточка — подсказка для проверки, а не правильный ответ.",
        "Отметьте естественность и смысл; другие материалы тоже могут подходить.",
        "",
    ]
    for i, row in enumerate(rows, 1):
        lines.extend(
            [
                f"## {i}. {row['scenario']} · {row['split']}",
                "",
                f"- Запрос: {escape(row['query'])}",
                f"- Исходный материал: {escape(row['source_title'] or 'не задан')}",
                "- [ ] Запрос понятный и естественный",
                "- [ ] Исходный материал подходит или частично подходит",
                "- [ ] Требуется исправление или уточнение",
                "- Комментарий:",
                "",
            ]
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="artifacts/catalog")
    parser.add_argument(
        "--output", required=True, type=Path, help="New directory; never overwritten"
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--review-size", type=int, default=120)
    args = parser.parse_args()
    if not 0 <= args.review_size <= 10000:
        parser.error("--review-size must be between 0 and 10000")
    if args.output.exists():
        parser.error("Output already exists; choose a new directory")
    _, manifest, catalog = load_bundle(args.catalog)
    protected = protected_from_files(PROTECTED)
    rows, report = build_dataset(catalog, args.seed, *protected)
    if not rows:
        raise ValueError("No valid synthetic queries generated")
    queries = jsonl(rows)
    title_by_id = {item["entity_key"]: item.get("title", "") for item in catalog}
    review_rows = review_sample(rows, args.seed, args.review_size)
    for row in review_rows:
        row["source_title"] = title_by_id.get(row["source_id"])
    review = jsonl(review_rows)
    review_md = review_markdown(review_rows)
    result_manifest = {
        "schema_version": 1,
        "generator_version": VERSION,
        "seed": args.seed,
        "review_size": args.review_size,
        "catalog_sha256": manifest["catalog_sha256"],
        "queries_sha256": hashlib.sha256(queries.encode("utf-8")).hexdigest(),
        "review_sha256": hashlib.sha256(review.encode("utf-8")).hexdigest(),
        "review_markdown_sha256": hashlib.sha256(review_md.encode("utf-8")).hexdigest(),
        "protected_files": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in PROTECTED
        },
        "generator_files": {
            name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
            for name in (
                "src/alfa_reco/synthetic.py",
                "src/alfa_reco/synthetic_scenarios.py",
                "scripts/generate_synthetic.py",
            )
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".synthetic-", dir=args.output.parent))
    try:
        (staging / "queries.jsonl").write_text(queries, encoding="utf-8")
        (staging / "review.jsonl").write_text(review, encoding="utf-8")
        (staging / "review.md").write_text(review_md, encoding="utf-8")
        (staging / "manifest.json").write_text(
            json.dumps(result_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (staging / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        # Reserve the destination atomically: never replace even an empty directory.
        args.output.mkdir()
        for name in ("queries.jsonl", "review.jsonl", "review.md", "report.json", "manifest.json"):
            os.rename(staging / name, args.output / name)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    print(json.dumps({"output": str(args.output), **report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
