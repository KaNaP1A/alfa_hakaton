import unittest

from test_suggestions import material

from alfa_reco.confidence import assess_results
from alfa_reco.personalization import clarification, recommend
from alfa_reco.query_rules import plan_query
from alfa_reco.text import embedding_query


class NewUserTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [
            material("article:1", "Налоги кофейни", ["Финансы и учет"]),
            material("article:2", "Как платить налоги кофейни", ["Финансы и учет"]),
            material("article:3", "Налоги работников", ["Управление командой"]),
            material("article:4", "Идеи продвижения", ["Маркетинг"]),
        ]

    def test_no_profile_no_invented_personalization(self):
        self.assertEqual(recommend(self.catalog, [], []), [])

    def test_preferences_and_activity_are_independent_inputs(self):
        result = recommend(self.catalog, ["marketing"], ["article:1"])
        self.assertEqual(result[0]["entity_key"], "article:2")
        self.assertIn("Налоги кофейни", result[0]["reason"])
        self.assertTrue(any(x["entity_key"] == "article:4" for x in result))
        self.assertTrue(all(x["entity_key"] != "article:1" for x in result))

    def test_invalid_unknown_or_cross_generation_item_is_rejected(self):
        for categories, viewed in [(["bogus"], []), ([], ["bad"]), ("marketing", [])]:
            with self.subTest(categories=categories, viewed=viewed):
                with self.assertRaises(ValueError):
                    recommend(self.catalog, categories, viewed)

    def test_common_action_and_legal_form_are_not_thematic_overlap(self):
        catalog = [
            material("article:tax", "Налоговая задолженность ИП: как проверить", ["Законы"]),
            material("article:diploma", "Как проверить диплом ИП", ["Законы"]),
            material("article:taxes", "Налоговая система ИП", ["Законы"]),
        ]
        result = recommend(catalog, [], ["article:tax"])
        self.assertEqual([row["entity_key"] for row in result], ["article:taxes"])

    def test_clarification_only_for_short_unnegated_query(self):
        self.assertIsNotNone(clarification("налоги", self.catalog))
        self.assertIsNone(clarification("налоги не сотрудников", self.catalog))
        self.assertIsNone(
            clarification("подробно изучить правила расчета налогов компании", self.catalog)
        )
        self.assertIsNone(clarification("налоги", self.catalog[:1]))

    def test_missing_context_is_not_limited_to_two_subject_words(self):
        for query in (
            "хочу открыть табачный магазин",
            "хочу открыть маленькую семейную пекарню",
            "помогите открыть собственный магазин спортивной одежды",
        ):
            with self.subTest(query=query):
                self.assertIsNotNone(clarification(query, self.catalog, needs_context=True))
        self.assertIsNone(
            clarification("не показывать курсы по налогам", self.catalog, needs_context=True)
        )

    def test_uncertainty_is_not_a_probability(self):
        self.assertEqual(assess_results([], [plan_query("кофейня")])["status"], "uncertain")
        self.assertEqual(assess_results([{}], [plan_query("кофейня")])["status"], "unvalidated")
        self.assertEqual(
            assess_results([{}], [plan_query("бесплатный курс")])["status"], "uncertain"
        )

    def test_order_sensitive_text_is_not_sorted(self):
        for query in ["перевод от клиента", "не открывать магазин", '"цвет кофе"']:
            self.assertEqual(embedding_query(query), query)

    def test_compound_contrast_is_not_claimed_resolved(self):
        for query in [
            "удержать клиентов, а не сотрудников но только удалённых",
            "не только маркетинг, а также продажи",
        ]:
            plan = plan_query(query)
            self.assertFalse(plan.contrast_applied)
            self.assertTrue(plan.unresolved_negation)

    def test_duration_is_reported_as_unverified(self):
        self.assertIn("duration", plan_query("маркетинг за 2 часа").unsupported_constraints)
