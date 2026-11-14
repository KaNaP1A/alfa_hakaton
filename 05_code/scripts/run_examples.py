"""Observed search examples, not a labeled quality benchmark. Run from 05_code."""

import json
from pathlib import Path

from alfa_reco.search import SearchEngine

engine = SearchEngine("artifacts/catalog", semantic=True)
queries = [
    "Хочу открыть кофейню",
    "Как повысить лояльность сотрудников",
    "Безопасная разработка Frontend",
    "Нужен шаблон договора аренды",
]
results = [engine.search(query, mode="ensemble", top=3) for query in queries]
for result in results:
    print(result["query"])
    for row in result["results"]:
        print(" -", row["title"], row["scores"])
Path("artifacts/search_examples.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
)
