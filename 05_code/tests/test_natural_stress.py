import json
import unittest
from pathlib import Path
from unittest.mock import patch

from audit_stress_origins import summarize_exposure
from build_natural_stress_suite import build
from build_natural_style_suite import build as build_styles
from evaluate_natural_stress import summarize
from prepare_persona_corpus import normalize


class NaturalStressTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [{"entity_key": "article:1", "title": "Управление семейным бюджетом"}]
        self.cases = [
            {
                "id": "n01",
                "family": "finance",
                "split": "test",
                "query": "Как разобраться с расходами?",
            }
        ]
        self.variants = {
            "n01": [
                "Денег не хватает к зарплате",
                "Как планировать траты?",
                "Куда уходят мои деньги?",
            ]
        }
        self.targets = {"n01": ["article:1"]}

    def build_mock(self):
        with (
            patch("build_natural_stress_suite.VARIANTS", self.variants),
            patch("build_natural_stress_suite.TARGETS", self.targets),
        ):
            return build(self.catalog, self.cases)

    def test_variants_preserve_family_and_provisional_provenance(self):
        result = self.build_mock()
        self.assertEqual(len(result), 4)
        self.assertEqual({r["family"] for r in result}, {"finance"})
        self.assertTrue(all(not r["human_verified"] for r in result))
        self.assertTrue(all(r["known_targets"] == ["article:1"] for r in result))

    def test_duplicate_paraphrase_is_rejected(self):
        self.variants["n01"][0] = self.cases[0]["query"].upper()
        with self.assertRaisesRegex(ValueError, "Duplicate query"):
            self.build_mock()

    def test_full_title_copy_is_rejected(self):
        self.variants["n01"][0] = "Подскажи про управление семейным бюджетом"
        with self.assertRaisesRegex(ValueError, "full target title"):
            self.build_mock()

    def test_unknown_target_is_rejected(self):
        self.targets["n01"] = ["article:missing"]
        with self.assertRaisesRegex(ValueError, "Unknown target"):
            self.build_mock()

    def test_summary_reports_known_target_without_inventing_other_labels(self):
        rows = [
            {
                "models": {
                    "m": {
                        "known_target_shown": True,
                        "known_target_retrieved": True,
                        "result_ids": ["a", "b"],
                    }
                }
            },
            {
                "models": {
                    "m": {
                        "known_target_shown": False,
                        "known_target_retrieved": True,
                        "result_ids": ["b", "b"],
                    }
                }
            },
            {
                "models": {
                    "m": {
                        "known_target_shown": False,
                        "known_target_retrieved": False,
                        "result_ids": [],
                    }
                }
            },
        ]
        result = summarize(rows, "m")
        self.assertEqual(result["queries"], 3)
        self.assertEqual(result["known_target_shown_top5"], 1)
        self.assertEqual(result["known_target_retrieved"], 2)
        self.assertEqual(result["empty_results"], 1)
        self.assertEqual(result["duplicate_result_queries"], 1)
        self.assertAlmostEqual(result["known_target_shown_rate"], 1 / 3)

    def test_recorded_stress_set_has_distinct_queries_and_explicit_provenance(self):
        path = (
            Path(__file__).resolve().parents[2]
            / "data/relevance_review/natural_stress_20261115.json"
        )
        rows = json.loads(path.read_text())["queries"]
        self.assertEqual(len(rows), 80)
        self.assertEqual(len({r["family"] for r in rows}), 20)
        self.assertEqual(len({normalize(r["query"]) for r in rows}), 80)
        self.assertTrue(all(r["known_targets"] and not r["human_verified"] for r in rows))

    def test_controlled_styles_preserve_the_same_target_and_provenance(self):
        source = [
            {
                "id": "q1",
                "query": "Как спланировать расходы?",
                "known_targets": ["article:1"],
                "human_verified": False,
            }
        ]
        rows = build_styles(source)
        self.assertEqual({r["style"] for r in rows}, {"original", "polite", "beginner"})
        self.assertTrue(
            all(
                r["base_id"] == "q1"
                and r["known_targets"] == ["article:1"]
                and not r["human_verified"]
                for r in rows
            )
        )
        self.assertEqual(source[0]["query"], "Как спланировать расходы?")

    def test_controlled_styles_reject_duplicates_and_unverified_provenance(self):
        row = {
            "id": "q1",
            "query": "Вопрос о бюджете",
            "known_targets": ["article:1"],
            "human_verified": False,
        }
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            build_styles([row, {**row, "id": "q2"}])
        with self.assertRaisesRegex(ValueError, "provisional"):
            build_styles([{**row, "human_verified": True}])

    def test_source_exposure_counts_cards_and_distinct_queries(self):
        catalog = [
            {"entity_key": "a"},
            {"entity_key": "b", "experiment_origin": "public_snapshot"},
        ]
        rows = [
            {"models": {"m": {"result_ids": ["a", "b"]}}},
            {"models": {"m": {"result_ids": ["b"]}}},
            {"models": {"m": {"result_ids": []}}},
        ]
        result = summarize_exposure(rows, catalog)["m"]
        self.assertEqual(result["shown_cards"], 3)
        self.assertEqual(result["origin_counts"], {"backup": 1, "public_snapshot": 2})
        self.assertEqual(result["queries_with_origin"], {"backup": 1, "public_snapshot": 2})
        self.assertAlmostEqual(result["origin_shares"]["public_snapshot"], 2 / 3)

    def test_source_exposure_refuses_unknown_or_repeated_cards(self):
        catalog = [{"entity_key": "a"}]
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            summarize_exposure([{"models": {"m": {"result_ids": ["a", "a"]}}}], catalog)
        with self.assertRaisesRegex(ValueError, "catalog"):
            summarize_exposure([{"models": {"m": {"result_ids": ["missing"]}}}], catalog)


if __name__ == "__main__":
    unittest.main()
