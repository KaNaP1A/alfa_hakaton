import copy
import importlib.util
import unittest
from unittest.mock import patch

from test_suggestions import material

from alfa_reco.personalization import recommend
from alfa_reco.profile import recommend_for_profile


class Engine:
    generation = "test-generation"

    def __init__(self, catalog):
        self.catalog = catalog

    def search(self, *args, **kwargs):
        raise AssertionError("No-goal cold start should not run search")


class ColdStartTests(unittest.TestCase):
    def profile(self, **fields):
        return {"generation": "test-generation", **fields}

    def test_empty_profile_offers_only_existing_directions_without_inventing_results(self):
        engine = Engine([material("article:1", "Продажи", ["Продажи"])])
        result = recommend_for_profile(engine, self.profile())
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["results"], [])
        self.assertTrue(result["onboarding"]["allow_goal_text"])
        self.assertEqual([x["category"] for x in result["onboarding"]["options"]], ["marketing"])

    def test_no_matching_facets_asks_for_a_goal_even_with_other_preferences(self):
        engine = Engine([material("article:1", "Продажи", ["Продажи"])])
        result = recommend_for_profile(engine, self.profile(categories=["team"], preferred_kinds=["course"]))
        self.assertEqual(result["results"], [])
        self.assertIsNotNone(result["onboarding"])

    def test_category_title_evidence_wins_over_identifier_and_order(self):
        catalog = [
            material("article:aaa", "Общие советы", ["Маркетинг"]),
            material("article:zzz", "Маркетинг для малого бизнеса", ["Маркетинг"]),
        ]
        profile = self.profile(categories=["marketing"])
        first = recommend_for_profile(Engine(catalog), profile)
        shuffled = recommend_for_profile(Engine(list(reversed(catalog))), profile)
        self.assertEqual(first["results"][0]["entity_key"], "article:zzz")
        self.assertEqual(first["results"], shuffled["results"])
        self.assertEqual(first["results"][0]["profile_evidence"]["matched_facets"], ["Маркетинг"])
        legacy_interface = recommend(catalog, ["marketing"], [], limit=5)
        self.assertEqual(legacy_interface[0]["entity_key"], "article:zzz")
        self.assertEqual(legacy_interface[0]["method"], "cold_start_facets_v1")

    def test_diversity_is_soft_and_never_adds_an_unrelated_facet(self):
        catalog = [
            material("article:a", "Маркетинг А", ["Маркетинг"]),
            material("article:b", "Маркетинг Б", ["Маркетинг"]),
            material("webinar:c", "Маркетинг В", ["Маркетинг"]),
            material("course:outside", "Договор аренды", ["Законы"]),
        ]
        result = recommend_for_profile(Engine(catalog), self.profile(categories=["marketing"]), limit=2)
        self.assertEqual({x["kind"] for x in result["results"]}, {"article", "webinar"})
        self.assertNotIn("course:outside", [x["entity_key"] for x in result["results"]])

    def test_tied_scores_use_content_before_identifier(self):
        catalog = [
            material("article:aaa", "Маркетинг", ["Маркетинг"], description="Описание Я"),
            material("article:zzz", "Маркетинг", ["Маркетинг"], description="Описание А"),
        ]
        result = recommend_for_profile(Engine(catalog), self.profile(categories=["marketing"]), limit=1)
        self.assertEqual(result["results"][0]["entity_key"], "article:zzz")

    def test_identical_text_is_flagged_but_not_suppressed_without_verified_identity(self):
        a = material("article:a", "Маркетинг", ["Маркетинг"], description="О рекламе", body="Текст")
        b = {**copy.deepcopy(a), "entity_key": "article:b", "source_id": "b"}
        c = {**copy.deepcopy(a), "entity_key": "article:c", "source_id": "c", "body": "Другой текст"}
        result = recommend_for_profile(Engine([a, b, c]), self.profile(categories=["marketing"]), limit=5)
        keys = [x["entity_key"] for x in result["results"]]
        self.assertEqual(len(keys), 3)
        self.assertIn("article:c", keys)
        for original in (x for x in result["results"] if x["entity_key"] != "article:c"):
            self.assertEqual(len(original["profile_evidence"]["possible_duplicate_entity_keys"]), 1)
            self.assertNotEqual(original["entity_key"], original["profile_evidence"]["possible_duplicate_entity_keys"][0])

    def test_verified_same_page_and_text_are_grouped_with_fallback_id(self):
        a = material("article:a", "Маркетинг", ["Маркетинг"], description="Описание", body="Текст",
                     canonical_url="https://kurs.alfabank.ru/articles/example/",
                     provenance={"canonical_url": "manual_public_page_2026-11-12"})
        b = {**copy.deepcopy(a), "entity_key": "article:b", "source_id": "b"}
        result = recommend_for_profile(Engine([a, b]), self.profile(categories=["marketing"]))
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(len(result["results"][0]["profile_evidence"]["possible_duplicate_entity_keys"]), 1)

    def test_same_title_and_description_without_full_text_is_not_deduplicated(self):
        a = material("course:a", "Маркетинг", ["Маркетинг"], description="Описание")
        b = {**copy.deepcopy(a), "entity_key": "course:b", "source_id": "b"}
        result = recommend_for_profile(Engine([a, b]), self.profile(categories=["marketing"]))
        self.assertEqual(len(result["results"]), 2)
        self.assertTrue(all(not x["profile_evidence"]["possible_duplicate_entity_keys"] for x in result["results"]))

    def test_distinct_access_types_are_not_assumed_duplicates(self):
        a = material("article:a", "Маркетинг", ["Маркетинг"], description="Описание", body="Текст")
        b = {**copy.deepcopy(a), "entity_key": "article:b", "source_id": "b", "access_type": "subscription"}
        result = recommend_for_profile(Engine([a, b]), self.profile(categories=["marketing"]))
        self.assertEqual(len(result["results"]), 2)

    def test_kind_and_industry_are_preferences_not_fabricated_constraints(self):
        catalog = [
            material("article:a", "Маркетинг", ["Маркетинг"]),
            material("course:b", "Маркетинг", ["Маркетинг"], industries=["Розница"]),
        ]
        result = recommend_for_profile(Engine(catalog), self.profile(
            categories=["marketing"], preferred_kinds=["course"], industry="ритейл"))
        self.assertEqual(result["results"][0]["entity_key"], "course:b")
        self.assertTrue(result["results"][0]["profile_evidence"]["industry"])
        self.assertEqual(len(result["results"]), 2)

    def test_generic_law_facet_alone_is_not_assumed_to_mean_finance(self):
        catalog = [
            material("article:employment", "Трудовой договор", ["Законы"]),
            material("article:tax", "Налоги ИП", ["Налоги и законы"]),
        ]
        result = recommend_for_profile(Engine(catalog), self.profile(categories=["finance"]))
        self.assertEqual([x["entity_key"] for x in result["results"]], ["article:tax"])
        only_general_law = recommend_for_profile(Engine(catalog[:1]), self.profile())
        self.assertNotIn("finance", [x["category"] for x in only_general_law["onboarding"]["options"]])

    def test_selected_category_offers_optional_specific_topics(self):
        catalog = [
            material("article:a", "Налоги", ["Налоги и законы"]),
            material("article:b", "Анализ", ["Финансовый анализ"]),
        ]
        result = recommend_for_profile(Engine(catalog), self.profile(categories=["finance"]))
        options = result["onboarding"]["options"]
        self.assertEqual({x["focus_facet"] for x in options}, {"Налоги и законы", "Финансовый анализ"})
        self.assertTrue(result["onboarding"]["allow_goal_text"])
        focused = recommend_for_profile(Engine(catalog), self.profile(
            categories=["finance"], focus_facet="финансовый анализ"))
        self.assertEqual([x["entity_key"] for x in focused["results"]], ["article:b"])
        self.assertEqual(focused["profile_usage"]["focus_facet"], "strict_catalog_facet_filter")
        with self.assertRaises(ValueError):
            recommend_for_profile(Engine(catalog), self.profile(categories=["finance"], focus_facet="Маркетинг"))

    def test_weak_diversity_or_format_does_not_override_stronger_title_signal(self):
        catalog = [
            material("article:a", "Маркетинг", ["Маркетинг"]),
            material("course:b", "Общие советы", ["Маркетинг"]),
        ]
        result = recommend_for_profile(Engine(catalog), self.profile(
            categories=["marketing"], preferred_kinds=["course"]))
        self.assertEqual(result["results"][0]["entity_key"], "article:a")

    def test_possible_geographic_hint_is_deferred_but_not_removed(self):
        catalog = [
            material("article:a", "Маркетинг во Владимире", ["Маркетинг"]),
            material("article:b", "Общие сведения", ["Маркетинг"]),
        ]
        def geo(title, region):
            return {"status": "possible_region_unknown" if "Владимир" in title else "not_detected",
                    "mentions": [], "verified": False}
        with patch("alfa_reco.cold_start.geographic_hint", side_effect=geo):
            result = recommend_for_profile(Engine(catalog), self.profile(categories=["marketing"]))
        self.assertEqual([x["entity_key"] for x in result["results"]], ["article:b", "article:a"])
        self.assertFalse(result["results"][1]["profile_evidence"]["geography"]["verified"])

    @unittest.skipUnless(importlib.util.find_spec("pymorphy3"), "Optional geography morphology")
    def test_actual_geographic_hint_and_unknown_scope(self):
        from alfa_reco.geography import geographic_hint

        self.assertEqual(geographic_hint("Бизнес во Владимире")["status"], "possible_region_unknown")
        self.assertEqual(geographic_hint("Бизнес во Владимире", "Владимир")["status"], "possible_match")
        self.assertEqual(geographic_hint("Бизнес во Владимире", "Москва")["status"], "possible_other_region")
        self.assertEqual(geographic_hint("Бизнес в России")["status"], "not_detected")
        self.assertEqual(geographic_hint("Объявление в Яндексе")["status"], "not_detected")

    def test_missing_morphology_is_reported_not_guessed(self):
        from alfa_reco.geography import geographic_hint

        with patch("alfa_reco.geography._analyzer", return_value=None):
            self.assertEqual(geographic_hint("Бизнес во Владимире", "Москва"), {
                "status": "unavailable", "mentions": [], "verified": False,
            })


if __name__ == "__main__":
    unittest.main()
