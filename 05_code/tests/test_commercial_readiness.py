import unittest

from scripts.audit_commercial_readiness import positive_snapshot_amount, summarize


class CommercialReadinessTests(unittest.TestCase):
    def test_amount_is_only_an_unverified_positive_number(self):
        for value in (None, "", "not a price", 0, -1, True, "NaN", "Infinity"):
            with self.subTest(value=value):
                self.assertFalse(positive_snapshot_amount(value))
        self.assertTrue(positive_snapshot_amount("3990"))

    def test_cost_and_entitlement_are_kept_separate(self):
        catalog = [
            {"kind": "course", "course_cost_available": True, "price_raw": None,
             "access_type": "subscription", "lessons": []},
            {"kind": "course", "course_cost_available": True, "price_raw": "3990",
             "access_type": "paid", "lessons": [{"title": "пример"}]},
            {"kind": "course", "access_type": "unknown"},
            {"kind": "article", "article_type_available": True, "access_type": "open"},
            {"kind": "glossary"},
        ]
        report = summarize(catalog)
        self.assertEqual(report["searchable_items"], 4)
        courses = report["by_kind"]["course"]
        self.assertEqual(courses["total"], 3)
        self.assertEqual(courses["snapshot_price_free"], 1)
        self.assertEqual(courses["snapshot_price_unknown"], 2)
        self.assertEqual(courses["positive_raw_amount_unverified"], 1)
        self.assertEqual(courses["free_cost_with_non_open_access"], 1)
        self.assertEqual(courses["visible_lesson_entries"], 1)
        self.assertNotIn("glossary", report["by_kind"])
        self.assertNotIn("пример", str(report))


if __name__ == "__main__":
    unittest.main()
