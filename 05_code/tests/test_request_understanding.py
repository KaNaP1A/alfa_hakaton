import tempfile
import unittest

from test_suggestions import enable_test_dense, material, write_bundle

from alfa_reco.request_understanding import (
    actions,
    analyze_request,
    opposite_title_intent,
    weak_intent_support,
)
from alfa_reco.retrieval import RankingConfig
from alfa_reco.search import SearchEngine


class RequestUnderstandingTests(unittest.TestCase):
    def test_explicit_format_and_currency_course_are_distinguished(self):
        for query, expected in (("курс по маркетингу", "course"), ("вебинар по налогам", "webinar"),
                                ("найди статью о налогах", "article")):
            with self.subTest(query=query):
                self.assertEqual(analyze_request(query)["format"], expected)
        for query in ("курс валют для бизнеса", "как создать курс по маркетингу", "не хочу курс по налогам"):
            self.assertIsNone(analyze_request(query)["format"])

    def test_unverified_conditions_and_ambiguous_format(self):
        request = analyze_request("платный вебинар по налогам для начинающих до 30 минут")
        self.assertEqual(set(request["unsupported_constraints"]), {"price", "experience", "duration"})
        self.assertEqual(request["audience_text"], "для начинающих")
        self.assertIn("duration", analyze_request("курс по налогам за неделю")["unsupported_constraints"])
        self.assertIn("experience", analyze_request("маркетинг без предварительного опыта")["unsupported_constraints"])
        ambiguous = analyze_request("курс или вебинар по маркетингу")
        self.assertIsNone(ambiguous["format"])
        self.assertIn("format", ambiguous["unsupported_constraints"])

    def test_narrow_opposite_actions_and_preventive_titles(self):
        retention = actions("как удержать сотрудников")
        self.assertTrue(opposite_title_intent(retention, "Как уволить сотрудника"))
        self.assertFalse(opposite_title_intent(retention, "Как избежать увольнения сотрудников"))
        self.assertFalse(opposite_title_intent(retention, "Увольнение и удержание сотрудников"))
        self.assertFalse(opposite_title_intent(actions("удержать налог с зарплаты сотрудника"),
                                               "Как уволить сотрудника"))
        collection = actions("как взыскать долг")
        self.assertTrue(opposite_title_intent(collection, "Как погасить задолженность"))
        self.assertFalse(opposite_title_intent(collection, "Как взыскать долг"))

    def test_weak_retention_evidence_needs_specific_support(self):
        for query in ("как удержать сотрудников", "уменьшить текучесть кадров"):
            signal = actions(query)
            article = material("article:a", "Почему сотрудники массово увольняются и что с этим делать")
            team = material("course:b", "Как управлять командой", description="Чтобы сотрудники были довольны")
            vacation = material("article:c", "Как отправить сотрудника в отпуск")
            legal = material("document:d", "Уведомление об отсутствии вакансий",
                             description="Сотрудника увольняют по сокращению штата")
            self.assertEqual(weak_intent_support(signal, article, 0.81), "title")
            self.assertEqual(weak_intent_support(signal, team, 0.81), "related_team_context")
            self.assertIsNone(weak_intent_support(signal, vacation, 0.83))
            self.assertIsNone(weak_intent_support(signal, legal, 0.83))
            self.assertIsNone(weak_intent_support(signal, article, 0.799))
            self.assertIsNone(weak_intent_support(signal, article, 0.81, conflict=True))
            self.assertIsNone(weak_intent_support(signal, material("article:e", "Как не удержать сотрудников"), 0.83))
        self.assertIsNone(weak_intent_support(actions("удержать налог из зарплаты сотрудника"), article, 0.81))


class SearchUnderstandingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        write_bundle(temp.name, [
            material("article:marketing", "Маркетинг для бизнеса"),
            material("course:marketing", "Маркетинг для бизнеса"),
            material("webinar:marketing", "Маркетинг для бизнеса"),
            material("article:currency", "Курс валют для бизнеса"),
            material("article:collect", "Как взыскать долг"),
            material("article:repay", "Как погасить долг"),
        ])
        self.engine = enable_test_dense(SearchEngine(temp.name))

    def test_explicit_format_filters_all_results_and_keeps_original_query(self):
        for query, kind in (("курс по маркетингу", "course"), ("вебинар по маркетингу", "webinar")):
            with self.subTest(query=query):
                result = self.engine.search(query, mode="hybrid")
                self.assertEqual(result["query"], query)
                self.assertTrue(result["results"])
                self.assertTrue(all(item["kind"] == kind for item in result["results"]))
                self.assertEqual(result["request_understanding"]["applied_format"], kind)
                self.assertEqual(result["request_understanding"]["model_query"], "маркетингу")

    def test_unknown_constraints_stay_visible_with_material_focus(self):
        query = "бесплатный курс по маркетингу для начинающих"
        token = self.engine.clarifications.issue(query, {"kind": "material", "value": "article:marketing"})
        result = self.engine.search(query, mode="hybrid", clarification_token=token)
        self.assertEqual(result["results"][0]["entity_key"], "article:marketing")
        self.assertEqual(result["confidence"]["status"], "uncertain")
        self.assertTrue({"price", "experience", "format"} <= set(result["query_rules"]["unsupported_constraints"]))
        self.assertTrue(result["request_understanding"]["format_conflict"])

    def test_conflicting_explicit_kind_is_reported(self):
        result = self.engine.search("вебинар по маркетингу", mode="hybrid", kind="course")
        self.assertEqual(result["confidence"]["status"], "uncertain")
        self.assertIn("format", result["query_rules"]["unsupported_constraints"])
        self.assertTrue(all(item["kind"] == "course" for item in result["results"]))

    def test_multiple_formats_offer_clarification(self):
        result = self.engine.search("курс или вебинар по маркетингу", mode="hybrid")
        self.assertEqual(result["confidence"]["status"], "uncertain")
        self.assertTrue(result["clarification"]["allow_text"])
        self.assertIn("format", result["query_rules"]["unsupported_constraints"])

    def test_opposite_debt_intent_is_excluded_from_main_and_alternatives(self):
        self.engine.dense_signals = lambda query: {
            source: [0.9] * len(self.engine.catalog) for source in ("card", "body", "lesson")
        }
        result = self.engine.search("как взыскать долг", mode="hybrid")
        self.assertIn("article:collect", [item["entity_key"] for item in result["results"]])
        self.assertNotIn("article:repay", [item["entity_key"] for item in result["results"] + result["alternatives"]])

    def test_contrast_with_ambiguous_pronoun_asks_before_excluding_referent(self):
        query = "не хочу увольнять сотрудников, а хочу удержать их"
        result = self.engine.search(query, mode="hybrid")
        self.assertFalse(result["results"])
        self.assertFalse(result["alternatives"])
        self.assertEqual(result["confidence"]["reason"], "unresolved_negation")
        self.assertTrue(result["query_rules"]["unresolved_negation"])
        self.assertTrue(result["clarification"]["allow_text"])
        clarified = self.engine.search(query, mode="hybrid", clarification_text="сотрудников")
        self.assertFalse(clarified["query_rules"]["unresolved_negation"])

    def test_contrast_does_not_exclude_synonymous_employee_referent(self):
        query = "не хочу увольнять сотрудников, а хочу удержать персонал"
        result = self.engine.search(query, mode="hybrid")
        self.assertFalse(result["results"])
        self.assertTrue(result["query_rules"]["unresolved_negation"])
        self.assertTrue(result["clarification"]["allow_text"])

    def test_weaker_semantic_candidate_is_labeled_and_specific_title_wins(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        write_bundle(temp.name, [
            material("article:vacation", "Как отправить сотрудника в отпуск"),
            material("course:team", "Как управлять командой", description="Чтобы сотрудники были довольны"),
            material("article:attrition", "Почему сотрудники массово увольняются и что с этим делать"),
            material("document:layoff", "Уведомление об отсутствии вакансий",
                     description="Сотрудника увольняют по сокращению штата"),
        ])
        engine = SearchEngine(temp.name)

        class Backend:
            config = RankingConfig()
            policy = {"semantic_min": 0.84, "strong_semantic_min": 0.92, "lexical_min": 0.85}
            exact_mode = False

            def result(self, query, allowed, selected):
                dense = {"card": [0.83] * 4, "body": [0] * 4, "lesson": [0] * 4}
                signals = engine.retriever.signals(query, dense)
                _, lexical, _, fused, ranks = engine.retriever.rank(signals, self.config, allowed)
                return {"view": {"normalization": "test", "canonicalized": False}, "signals": signals,
                        "dense": dense, "ranked": [0, 1, 2, 3], "lexical": lexical, "fused": fused,
                        "ranks": ranks, "model_scores": {i: float(4 - i) for i in range(4)}}

            def support(self, prepared, i, selected=False, conflict=False):
                exact = self.exact_mode and i == 1
                return {"admitted": exact, "alternative": False, "card_coverage": 0.2,
                        "card_cosine": 0.83, "exact_title": exact, "explicit_selection": selected}

        engine._relevance = Backend()
        result = engine.search("как удержать сотрудника", mode="relevance")
        self.assertEqual([item["entity_key"] for item in result["results"]], ["article:attrition", "course:team"])
        self.assertEqual(result["confidence"]["reason"], "weak_intent_match")
        self.assertTrue(all(item["support"]["weak_intent_match"] for item in result["results"]))
        self.assertIn("unexpanded_card_coverage", result["results"][0]["support"])
        self.assertEqual(result["retrieval_diagnostics"]["shown_results"], 2)
        engine._relevance.exact_mode = True
        exact = engine.search("как удержать сотрудника", mode="relevance")
        self.assertEqual(exact["results"][0]["entity_key"], "course:team")


if __name__ == "__main__":
    unittest.main()
