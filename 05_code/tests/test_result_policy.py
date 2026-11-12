import tempfile
import unittest

from test_suggestions import material, write_bundle

from alfa_reco.clarifications import ClarificationTokens
from alfa_reco.eligibility import candidate_support
from alfa_reco.personalization import recommend
from alfa_reco.promotions import content_fingerprint, promotion_for
from alfa_reco.search import SearchEngine


class ResultPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.catalog = [
            material("article:ip", "Как открыть ИП"),
            material("article:ooo", "Как открыть ООО"),
            material("article:cafe", "Как открыть кофейню"),
            material("glossary:cafe", "Кофейня"),
        ]
        write_bundle(self.temp.name, self.catalog)
        self.engine = SearchEngine(self.temp.name)

    def test_unsupported_subject_is_not_filled_with_same_generic_verb(self):
        result = self.engine.search("хочу открыть столовую", mode="bm25")
        self.assertEqual(result["results"], [])
        self.assertIsNotNone(result["clarification"])

    def test_three_word_subject_gets_a_question_when_results_are_insufficient(self):
        result = self.engine.search("хочу открыть табачный магазин", mode="bm25")
        self.assertIsNotNone(result["clarification"])
        exact = self.engine.search("Как открыть ИП", mode="bm25")
        self.assertIsNone(exact["clarification"])

    def test_material_choice_changes_focus_and_keeps_original_query(self):
        query = "хочу открыть столовую"
        result = self.engine.search(query, mode="bm25")
        option = next(
            x for x in result["clarification"]["options"] if x["label"] == "Как открыть ИП"
        )
        focused = self.engine.search(query, mode="bm25", clarification_token=option["token"])
        self.assertEqual(focused["query"], query)
        self.assertEqual(focused["focus"]["label"], "Как открыть ИП")
        self.assertEqual(focused["results"][0]["entity_key"], "article:ip")
        self.assertEqual(focused["confidence"]["status"], "unvalidated")
        self.assertIsNone(focused["clarification"])
        with self.assertRaises(ValueError):
            self.engine.search(
                "изменённая задача", mode="bm25", clarification_token=option["token"]
            )

    def test_selection_is_not_accepted_after_restart_or_tampering(self):
        option = {"kind": "material", "value": "article:ip"}
        token = self.engine.clarifications.issue("открыть", option)
        another = ClarificationTokens(self.engine.generation, self.catalog)
        for tampered in [token[:-3] + "abc", "garbage", "", "a" * 2049]:
            with self.subTest(token=tampered[:10]):
                with self.assertRaises(ValueError):
                    another.resolve("открыть", tampered)
        with self.assertRaises(ValueError):
            another.resolve("открыть", token)

    def test_glossary_is_excluded_from_search_and_suggestions(self):
        result = self.engine.search("кофейня", mode="bm25", top=5)
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["kind"], "article")
        suggestions = self.engine.suggest("кофейня")
        for group in ("completions", "related_topics"):
            for row in suggestions[group]:
                keys = self.engine.suggestions.resolve(row["id"], suggestions["generation"])[
                    "entity_keys"
                ]
                self.assertNotIn("glossary:cafe", keys)
        with self.assertRaises(ValueError):
            self.engine.search("кофейня", mode="bm25", kind="glossary")

    def test_home_recommendations_exclude_glossary(self):
        catalog = [
            material("glossary:1", "Налоги", ["Финансы и учет"]),
            material("article:2", "Налоги бизнеса", ["Финансы и учет"]),
        ]
        result = recommend(catalog, ["finance"], [])
        self.assertEqual([item["entity_key"] for item in result], ["article:2"])

    def test_explicit_title_does_not_need_semantic_score(self):
        result = self.engine.search("Как открыть ИП", mode="bm25")
        self.assertEqual(result["results"][0]["entity_key"], "article:ip")
        self.assertEqual(result["confidence"]["status"], "unvalidated")

    def test_focus_cannot_silence_original_constraints(self):
        query = "бесплатный курс"
        token = self.engine.clarifications.issue(query, {"kind": "material", "value": "article:ip"})
        result = self.engine.search(query, mode="bm25", clarification_token=token)
        self.assertEqual(result["confidence"]["reason"], "unverified_constraint")
        self.assertIn("price", result["query_rules"]["unsupported_constraints"])

    def test_weak_semantic_candidates_and_accidental_word_matches_are_dropped(self):
        item = material("article:other", "Как открыть ООО")
        self.assertFalse(candidate_support("открыть кофейню", item, 0.30)["admitted"])
        self.assertFalse(candidate_support("открыть кофейню", item, 0.30)["alternative"])
        self.assertFalse(candidate_support("frontend", item, 0.9)["admitted"])
        self.assertTrue(candidate_support("кофейня", self.catalog[2], 0.65)["admitted"])
        self.assertFalse(candidate_support("кофейня", self.catalog[3], 0.9)["admitted"])

    def test_promotion_is_separate_copy_and_invalidates_on_source_change(self):
        item = material(
            "article:436d99ec-50d7-4abc-a0ed-ddd2f7d122d9",
            "Как открыть ИП",
            description="Что такое код ОКВЭД, какой налоговой режим выбрать, как подать и подписать все документы онлайн",
        )
        copy = promotion_for(item)
        self.assertEqual(copy["source"], "reviewed_catalog_copy")
        self.assertNotEqual(copy["text"], item["description"])
        self.assertNotIn("Для задачи", copy["text"])
        self.assertNotIn("CatBoost", copy["text"])
        changed = {**item, "description": "Новое содержание"}
        self.assertNotEqual(content_fingerprint(item), content_fingerprint(changed))
        self.assertEqual(promotion_for(changed)["source"], "title_template")
