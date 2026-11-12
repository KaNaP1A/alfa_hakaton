import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_suggestions import material

from alfa_reco.lab import lab_data
from alfa_reco.personalization import recommend


class HistoryContracts(unittest.TestCase):
    def test_every_viewed_item_is_excluded_even_beyond_scoring_window(self):
        catalog = [
            material(f"article:{i}", "Управление денежным потоком", ["Финансы"]) for i in range(40)
        ]
        history = [i["entity_key"] for i in catalog[:30]]
        result = recommend(catalog, [], history, limit=20)
        self.assertTrue(result)
        self.assertFalse(set(history) & {i["entity_key"] for i in result})

    def test_limit_is_integer_and_bounded(self):
        for limit in [False, True, 0, 21, "5", 1.5]:
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                recommend([], [], [], limit)

    def test_all_material_formats_can_supply_history(self):
        for kind in ["course", "webinar", "podcast", "article", "document"]:
            cat = [
                material(f"{kind}:a", "Денежный поток", ["Финансы"]),
                material("article:b", "Планирование денежного потока", ["Финансы"]),
                material("article:c", "Акварельный портрет", ["Искусство"]),
            ]
            with self.subTest(kind=kind):
                out = recommend(cat, [], [f"{kind}:a"])
                self.assertEqual([i["entity_key"] for i in out], ["article:b"])

    def test_repeated_views_do_not_multiply_preference(self):
        cat = [
            material("course:a", "Денежный поток", ["Финансы"]),
            material("article:b", "Денежный поток", ["Финансы"]),
        ]
        self.assertEqual(recommend(cat, [], ["course:a"]), recommend(cat, [], ["course:a"] * 20))

    def test_generic_title_words_are_not_shared_subjects(self):
        cat = [
            material("webinar:a", "Нововведения ВЭД: всё, что вы боялись спросить", ["Бизнес"]),
            material("article:b", "Всё о цифровом рубле", ["Бизнес"]),
            material("article:c", "Ваш бизнес: ликвидация ООО", ["Бизнес"]),
            material("article:d", "Нововведения ВЭД для импортёров", ["Бизнес"]),
        ]
        self.assertEqual(
            [i["entity_key"] for i in recommend(cat, [], ["webinar:a"])], ["article:d"]
        )

    def test_semantic_history_can_link_distinct_titles(self):
        import numpy as np

        cat = [
            material("course:a", "Управление командой", ["Команда"]),
            material("webinar:b", "Мотивация работников", ["Команда"]),
            material("article:c", "Акварель", ["Искусство"]),
        ]
        vec = np.array([[1.0, 0], [0.98, 0.2], [0, 1.0]])
        out = recommend(cat, [], ["course:a"], vectors=vec)
        self.assertEqual(out[0]["entity_key"], "webinar:b")
        self.assertEqual(out[0]["method"], "content_e5_and_facets")

    def test_profiles_do_not_share_mutable_state(self):
        cat = [
            material("course:a", "Денежный поток", ["Финансы"]),
            material("webinar:b", "Управление денежным потоком", ["Финансы"]),
            material("article:c", "Акварель", ["Искусство"]),
        ]
        before = recommend(cat, [], ["course:a"])
        recommend(cat, ["marketing"], ["article:c"])
        self.assertEqual(before, recommend(cat, [], ["course:a"]))


class LabDataContracts(unittest.TestCase):
    def test_missing_pool_is_a_clear_input_error(self):
        with tempfile.TemporaryDirectory() as temp, patch("alfa_reco.lab.ROOT", Path(temp)):
            with self.assertRaisesRegex(ValueError, "подготовлен"):
                lab_data("/lab/pool", {})

    def test_report_does_not_open_sealed_test_cases(self):
        with tempfile.TemporaryDirectory() as temp, patch("alfa_reco.lab.ROOT", Path(temp)):
            p = Path(temp) / "artifacts/challenge_v2"
            p.mkdir(parents=True)
            (p / "manifest.json").write_text(json.dumps({"test_status": "sealed_not_evaluated"}))
            (p / "test.jsonl").write_text("DO NOT OPEN")
            out = lab_data("/lab/data", {})
            self.assertEqual(out["challenge"]["test_status"], "sealed_not_evaluated")
            self.assertEqual(out["reports"], {})

    def test_export_template_includes_unjudged_pairs(self):
        with tempfile.TemporaryDirectory() as temp, patch("alfa_reco.lab.ROOT", Path(temp)):
            p = Path(temp) / "artifacts/annotation_pool/relevance_v1"
            p.mkdir(parents=True)
            rows = [
                {
                    "query_id": "q",
                    "entity_key": str(i),
                    "reviewer_a": None,
                    "reviewer_b": None,
                    "adjudicated": None,
                }
                for i in range(3)
            ]
            (p / "judgments.jsonl").write_text("\n".join(map(json.dumps, rows)))
            self.assertEqual(lab_data("/lab/template", {})["judgments"], rows)


if __name__ == "__main__":
    unittest.main()
