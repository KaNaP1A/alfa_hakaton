"""Smoke scenarios and warm autocomplete timing, not relevance metrics."""

import json
import statistics
import time
from pathlib import Path

from alfa_reco.search import SearchEngine

root = Path("artifacts")
start = time.perf_counter()
engine = SearchEngine(root / "catalog")
load_ms = (time.perf_counter() - start) * 1000
queries = [
    "",
    "к",
    "кофе",
    "открыть коф",
    "кофеня",
    "договор арнеды",
    "лояльность сотруд",
    "Frontend",
    "zzzxxyy",
    "как повысить лояльность сотрудников",
]
results = [engine.suggest(query) for query in queries]
by_query = {row["query"]: row for row in results}
assert by_query["Frontend"]["status"] == "no_match"
assert by_query["zzzxxyy"]["status"] == "no_match"
assert by_query["к"]["status"] == "insufficient_input"
assert by_query["кофеня"]["typo_tolerant_match"]
assert by_query["открыть коф"]["completions"]
assert any("аренды" in row["label"] for row in by_query["договор арнеды"]["completions"])
assert any(
    row["label"] == "Управление командой" for row in by_query["лояльность сотруд"]["related_topics"]
)
selected = by_query["лояльность сотруд"]["related_topics"][0]
search = engine.search(
    "лояльность сотрудников",
    mode="relevance",
    selection_id=selected["id"],
    selection_generation=engine.generation,
)
assert search["query"] == "лояльность сотрудников"
assert any(row["selection_match"] for row in search["results"])
times = []
for _ in range(30):
    for query in queries:
        start = time.perf_counter()
        engine.suggest(query)
        times.append((time.perf_counter() - start) * 1000)
times.sort()
report = {
    "generation": engine.generation,
    "entry_count": len(engine.suggestions.entries),
    "load_ms": round(load_ms, 3),
    "timing_scope": "in-process, warm, no network/render",
    "sample_count": len(times),
    "p50_ms": round(statistics.median(times), 3),
    "p95_ms": round(times[int(len(times) * 0.95) - 1], 3),
    "max_ms": round(max(times), 3),
    "suggestions": results,
    "selected_search": search,
}
(root / "suggestion_examples.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(
    json.dumps(
        {
            key: value
            for key, value in report.items()
            if key not in {"suggestions", "selected_search"}
        },
        ensure_ascii=False,
        indent=2,
    )
)
for row in results:
    print(
        repr(row["query"]),
        row["status"],
        [item["label"] for item in row["completions"]],
        [item["label"] for item in row["related_topics"]],
    )
