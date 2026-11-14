"""Product regression for requests longer than two subject words; not relevance gold."""

from pathlib import Path

from alfa_reco.cli import atomic_json
from alfa_reco.search import SearchEngine

engine = SearchEngine("artifacts/catalog", semantic=True)
rows = []
for query in [
    "хочу открыть табачный магазин",
    "хочу открыть маленькую семейную пекарню",
    "помогите открыть собственный магазин спортивной одежды",
    "хочу открыть столовую",
    "Как открыть ИП",
]:
    result = engine.search(query, mode="ensemble")
    question = result["clarification"]
    row = {
        "query": query,
        "question": question["question"] if question else None,
        "options": [x["label"] for x in question["options"]] if question else [],
        "results": [x["title"] for x in result["results"]],
    }
    if query == "Как открыть ИП":
        assert question is None
    else:
        assert question is not None, query
    rows.append(row)
    print(row, flush=True)
atomic_json(
    Path("evaluation/clarification_regression.json"),
    {"developer_regression_not_gold": True, "cases": rows},
)
