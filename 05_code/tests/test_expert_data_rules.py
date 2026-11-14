import unittest

from alfa_reco.content import enrich_content
from alfa_reco.pricing import price_fact


class ExpertDataRulesTests(unittest.TestCase):
    def test_null_cost_is_free_only_for_known_course_field(self):
        self.assertEqual(price_fact({"kind": "course", "course_cost_available": True,
                                     "price_raw": None})["status"], "free")
        for item in ({"kind": "course", "price_raw": None},
                     {"kind": "course", "course_cost_available": True, "price_raw": "3990"},
                     {"kind": "article", "course_cost_available": True, "price_raw": None},
                     {"kind": "course", "course_cost_available": True}):
            self.assertEqual(price_fact(item)["status"], "unknown")
        self.assertFalse(price_fact({"kind": "course", "course_cost_available": True,
                                     "price_raw": None})["access_verified"])

    def test_article_price_uses_its_verified_type_not_its_null_cost(self):
        self.assertEqual(price_fact({"kind": "article", "access_type": "open"})["status"], "unknown")
        self.assertEqual(price_fact({"kind": "article", "access_type": "open",
                                     "article_type_available": True})["status"], "free")
        self.assertEqual(price_fact({"kind": "article", "access_type": "subscription",
                                     "article_type_available": True})["status"], "paid_or_subscription")

    def test_article_list_flag_is_not_text_access_and_document_text_is_sanitized(self):
        catalog = [
            {"kind": "article", "source_id": "a", "access_type": "open",
             "content_public_flag": "f", "provenance": {}},
            {"kind": "document", "source_id": "d", "provenance": {}},
            {"kind": "course", "source_id": "c", "provenance": {},
             "lessons": [{"lesson_id": "private", "is_trial": False},
                         {"lesson_id": "trial", "is_trial": True}]},
        ]
        articles = [{"ArticleId": "a", "Id": "a1", "HtmlContent": "<p>Текст статьи</p>"}]
        documents = [{"DocumentId": "d", "Id": "d1",
                      "HtmlContent": "<p>Текст документа</p><script>secret</script>"}]
        lessons = [{"LessonId": key, "Id": key, "HtmlContent": key}
                   for key in ("private", "trial")]
        result = enrich_content(catalog, articles, lessons, documents)
        self.assertEqual(catalog[0]["body"], "Текст статьи")
        self.assertEqual(catalog[1]["body"], "Текст документа")
        self.assertEqual(catalog[1]["provenance"]["body"], "DocumentEmbedItems.HtmlContent")
        self.assertEqual(catalog[2]["lessons"][0]["body"], "")
        self.assertEqual(catalog[2]["lessons"][1]["body"], "trial")
        self.assertEqual(result["document_bodies"], 1)
