import unittest

from alfa_reco.evidence import coverage_signal, evidence_for, subject_terms


class EvidenceTests(unittest.TestCase):
    def test_explanation_distinguishes_title_and_body(self):
        item = {
            "title": "Как закрыть счёт",
            "description": "Список документов",
            "body": "Погасите долги до закрытия счета.",
            "topics": [],
            "tags": [],
        }
        result = evidence_for(item, "закрытие долгов", {"bm25": 2})
        self.assertEqual(result["facts"][0]["field"], "title")
        self.assertEqual(result["facts"][1]["field"], "body")
        self.assertEqual(result["facts"][1]["query_words"], ["долгов"])
        self.assertEqual(result["facts"][1]["field_words"], ["долги"])
        self.assertEqual(result["channels"], ["bm25"])

    def test_no_match_is_not_claimed_to_be_no_relevant_result(self):
        self.assertEqual(coverage_signal("frontend", {"кофейн", "курс"}), "no_literal_match")
        self.assertEqual(coverage_signal("кофейня", {"кофейн"}), "unknown")
        self.assertEqual(coverage_signal("хочу", {"кофейн"}), "unknown")

    def test_experience_and_price_are_not_misrepresented_as_subject(self):
        self.assertNotIn("без", subject_terms("бесплатный курс по маркетингу без опыта"))
        self.assertNotIn("опыт", subject_terms("бесплатный курс по маркетингу без опыта"))
        self.assertIn("маркетинг", subject_terms("бесплатный курс по маркетингу без опыта"))

    def test_numeric_tokens_with_decimal_point_are_supported(self):
        item = {
            "title": "Раздел 26.5 налогового кодекса",
            "description": "",
            "body": "",
            "topics": [],
            "tags": [],
        }
        result = evidence_for(item, "порядок 26.5", {"bm25": 1})
        self.assertEqual(result["facts"][0]["query_words"], ["26.5"])

    def test_negation_and_additive_words_are_not_presented_as_subject(self):
        terms = subject_terms("не только продажи, а также маркетинг")
        self.assertNotIn("не", terms)
        self.assertNotIn("тольк", terms)
        self.assertNotIn("такж", terms)
        self.assertIn("маркетинг", terms)


if __name__ == "__main__":
    unittest.main()
