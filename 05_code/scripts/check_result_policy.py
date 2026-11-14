"""Targeted product regressions on the real local catalog; not gold relevance labels."""

import json
from pathlib import Path

from alfa_reco.cli import atomic_json
from alfa_reco.search import SearchEngine


def main():
    engine = SearchEngine("artifacts/catalog", semantic=True, llm_enabled=False)
    queries = [
        "хочу открыть столовую",
        "Как открыть ИП",
        "открыть кофейню",
        "закрытие долгов",
        "договор аренды",
        "frontend",
        "хочу изучать квантовую телепортацию",
        "удержать сотрудников",
        "как открыть пекарню с нуля",
        "бесплатный курс по маркетингу без опыта",
    ]
    rows = []
    for query in queries:
        result = engine.search(query, mode="ensemble", top=5)
        rows.append(
            {
                "query": query,
                "confidence": result["confidence"],
                "results": [
                    {
                        "title": item["title"],
                        "kind": item["kind"],
                        "support": item["support"],
                        "promotion": item["promotion"],
                    }
                    for item in result["results"]
                ],
                "alternatives": [item["title"] for item in result["alternatives"]],
            }
        )
        assert all(
            item["kind"] != "glossary" for item in result["results"] + result["alternatives"]
        )
        assert len(result["results"]) <= 5
    original = engine.search(queries[0], mode="ensemble")
    option = next(
        option
        for option in original["clarification"]["options"]
        if option["label"] == "Как открыть ИП"
    )
    selected = engine.search(queries[0], mode="ensemble", clarification_token=option["token"])
    assert selected["query"] == queries[0]
    assert selected["results"][0]["title"] == "Как открыть ИП"
    assert selected["confidence"]["status"] != "uncertain"
    assert not engine.search("frontend", mode="ensemble")["results"]
    assert not engine.search("хочу изучать квантовую телепортацию", mode="ensemble")["results"]
    pairs = []
    for first, second in [
        ("хочу открыть кофейню", "открыть кофейню хочу"),
        ("договор аренды", "аренды договор"),
    ]:
        one = engine.search(first, mode="ensemble")["results"]
        two = engine.search(second, mode="ensemble")["results"]
        assert one and two
        equal = [row["entity_key"] for row in one] == [row["entity_key"] for row in two]
        assert equal
        pairs.append({"first": first, "second": second, "same_order": equal})
    report = {
        "description": "Regression checks written by developer. These assertions are not independent judgments of relevance.",
        "catalog_generation": engine.generation,
        "queries": rows,
        "selection": {
            "original_query": selected["query"],
            "focus": selected["focus"],
            "confidence": selected["confidence"],
            "first_title": selected["results"][0]["title"],
        },
        "order_pairs": pairs,
    }
    atomic_json(Path("evaluation/result_policy_2026_11_12.json"), report)
    print(
        json.dumps(
            {
                "queries": len(rows),
                "counts": {row["query"]: len(row["results"]) for row in rows},
                "focused_first": selected["results"][0]["title"],
                "passed": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
