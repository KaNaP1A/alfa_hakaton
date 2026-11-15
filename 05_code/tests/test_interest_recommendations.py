import json
import tempfile
import unittest
from pathlib import Path

from alfa_reco.interests import recommend_by_interests
from alfa_reco.personalization import recommend


def item(key, title, topics=(), tags=(), kind="article"):
    return {"entity_key": key, "kind": kind, "title": title, "description": "",
            "topics": list(topics), "tags": list(tags), "industries": []}


class InterestRecommendationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / "config.json"
        self.config.write_text(json.dumps({"version": 1, "categories": {"business": ["Особая тема"]}}))
        self.catalog = [
            *[item(f"article:b{i:02}", f"Старт бизнеса {i:02}", ["Старт бизнеса"]) for i in range(30)],
            item("course:rare", "Курс по развитию", tags=[" Развитие   бизнеса "], kind="course"),
            item("article:extra", "Особая тема", tags=["Особая тема"]),
            item("article:tax", "Финансы", topics=["Финансы"]),
            item("article:law", "Законы", topics=["Законы"]),
            item("glossary:rare", "Термин", topics=["Развитие бизнеса"], kind="glossary"),
        ]

    def call(self, categories=None, facets=None, viewed=None, generation="g1"):
        return recommend_by_interests(
            self.catalog, generation, ["business"] if categories is None else categories,
            [] if facets is None else facets, [] if viewed is None else viewed,
            current_generation="g1", config_path=self.config,
        )

    def test_selection_filters_before_limit_and_preserves_material_type(self):
        result = self.call(facets=["развитие бизнеса"])
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual([x["entity_key"] for x in result["results"]], ["course:rare"])
        self.assertEqual(result["results"][0]["kind"], "course")
        self.assertEqual(result["results"][0]["tags"], [" Развитие   бизнеса "])
        self.assertEqual(result["applied_filters"]["selected_facets"], ["Развитие бизнеса"])

    def test_multiple_topics_or_history_and_empty_results(self):
        result = self.call(facets=["Развитие бизнеса", "Особая тема"])
        self.assertEqual({x["entity_key"] for x in result["results"]}, {"course:rare", "article:extra"})
        self.assertEqual(result["applied_filters"]["facet_mode"], "any")
        remaining = self.call(facets=["Развитие бизнеса", "Особая тема"], viewed=["course:rare"])
        self.assertEqual([x["entity_key"] for x in remaining["results"]], ["article:extra"])
        empty = self.call(facets=["Развитие бизнеса"], viewed=["course:rare"])
        self.assertEqual(empty["results"], [])
        self.assertEqual(empty["status"], "insufficient_evidence")

    def test_category_only_includes_explicit_additions_and_no_law_leak(self):
        extra_only = [self.catalog[-4], self.catalog[-3], self.catalog[-2]]
        result = recommend_by_interests(extra_only, "g1", ["business"], [], [],
                                         current_generation="g1", config_path=self.config)
        self.assertEqual([x["entity_key"] for x in result["results"]], ["article:extra"])
        finance = self.call(categories=["finance"])
        self.assertEqual([x["entity_key"] for x in finance["results"]], ["article:tax"])
        self.assertEqual(self.call(categories=[])["results"], [])

    def test_legacy_cold_start_order_unchanged_for_base_category(self):
        self.config.write_text('{"version": 1, "categories": {}}')
        self.assertEqual(self.call()["results"], recommend(self.catalog, ["business"], []))

    def test_two_categories_and_topic_compatibility(self):
        result = self.call(categories=["business", "finance"], facets=["Особая тема", "Финансы"])
        self.assertEqual({x["entity_key"] for x in result["results"]}, {"article:extra", "article:tax"})
        for categories, facets in [(["business"], ["Финансы"]), ([], ["Финансы"]),
                                   (["finance"], ["Законы"]), (["business"], ["Нет темы"])]:
            with self.subTest(categories=categories, facets=facets), self.assertRaises(ValueError):
                self.call(categories=categories, facets=facets)

    def test_invalid_payloads(self):
        cases = [
            {"categories": ["business", "business"]}, {"categories": ["unknown"]},
            {"categories": "business"}, {"categories": [None]},
            {"facets": "Старт бизнеса"}, {"facets": [1]}, {"facets": [""]},
            {"facets": ["x" * 151]}, {"facets": ["Старт бизнеса", " старт  бизнеса "]},
            {"facets": [str(i) for i in range(21)]}, {"viewed": "article:tax"},
            {"viewed": ["no-such-id"]}, {"viewed": [None]},
            {"viewed": ["article:tax"] * 51}, {"generation": "stale"},
        ]
        for values in cases:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.call(**values)


if __name__ == "__main__":
    unittest.main()
