import json
import tempfile
import unittest
from pathlib import Path

from demo_catalog.build_catalog import build, normalize_title


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.public = self.path / "public.jsonl"
        self.old = self.path / "old.json"
        self.old.write_text(
            json.dumps([{"entity_key": "article:1", "kind": "article"}])
        )
        self.record = {
            "kind": "article",
            "entity_key": "article:1",
            "source_id": "1",
            "source_url": "https://kurs.alfabank.ru/articles/a/",
            "title": "Тема\u2028тест",
            "description": "текст",
            "observed_at": "2026-11-15",
            "price_raw_meta": "999",
        }

    def write(self, *rows):
        self.public.write_text(
            "\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n"
        )

    def test_sources_and_fictional_prices_are_kept_separate(self):
        self.write(self.record)
        result = build(self.public, self.old)
        actual = result["items"][0]
        self.assertEqual(actual["title"], "Тема\u2028тест")
        self.assertEqual(actual["price"], {"status": "unknown"})
        self.assertEqual(actual["user_access"], "unknown")
        self.assertEqual(actual["purchase_price"], "unknown")
        self.assertTrue(actual["historical_id_match"])
        self.assertEqual(actual["provenance"]["observed_at"], "2026-11-15")
        self.assertTrue(actual["id"].startswith("public:"))
        self.assertEqual(result["audit"]["synthetic"], 48)
        for item in result["items"][1:]:
            self.assertEqual(item["origin"], "synthetic")
            self.assertIsNone(item["source_url"])
            self.assertIn(item["price"]["status"], {"fictional", "fictional_free"})

    def test_unverified_course_and_noindex(self):
        course = {
            **self.record,
            "kind": "course",
            "entity_key": None,
            "source_id": None,
            "source_url": "https://kurs.alfabank.ru/courses/test/",
        }
        hidden = {
            **self.record,
            "source_url": "https://kurs.alfabank.ru/articles/hidden/",
            "source_noindex_raw": True,
        }
        self.write(course, hidden)
        result = build(self.public, self.old)
        self.assertEqual(result["audit"]["public"]["missing_source_id"], 1)
        self.assertEqual(result["audit"]["public"]["excluded_noindex"], 1)
        self.assertFalse(result["items"][0]["historical_id_match"])

    def test_duplicate_and_untrusted_sources_are_rejected(self):
        self.write(self.record, self.record)
        with self.assertRaisesRegex(ValueError, "Duplicate source URL"):
            build(self.public, self.old)
        self.write({**self.record, "source_url": "https://attacker.invalid/a"})
        with self.assertRaisesRegex(ValueError, "Unexpected source URL"):
            build(self.public, self.old)
        self.write({**self.record, "entity_key": "article:other"})
        with self.assertRaisesRegex(ValueError, "Inconsistent"):
            build(self.public, self.old)

    def test_restores_calculators_and_webinars_without_claiming_real_prices(self):
        self.write(self.record)
        self.old.write_text(
            json.dumps(
                [
                    {
                        "entity_key": "webinar:1",
                        "kind": "webinar",
                        "title": "Вебинар",
                        "source_id": "1",
                    },
                    {
                        "entity_key": "calculator:1",
                        "kind": "calculator",
                        "title": "Калькулятор",
                        "source_id": "1",
                    },
                ]
            )
        )
        calc = self.path / "calculators.jsonl"
        calc.write_text(
            json.dumps(
                {
                    "entity_key": "calculator:1",
                    "kind": "calculator",
                    "source_id": "1",
                    "title": "Калькулятор",
                    "source_page": "https://kurs.alfabank.ru/calculators/",
                }
            )
            + "\n"
        )
        result = build(self.public, self.old, calc)
        calculators = [x for x in result["items"] if x["kind"] == "calculator"]
        webinars = [
            x
            for x in result["items"]
            if x["kind"] == "webinar" and x["origin"] == "historical_backup"
        ]
        self.assertEqual(len(calculators), 1)
        self.assertEqual(len(webinars), 1)
        for item in calculators + webinars:
            self.assertEqual(item["price"]["status"], "unknown")
            self.assertEqual(item["demo_offer"]["kind"], "fictional_simulation")
            self.assertLessEqual(
                item["demo_offer"]["cost_rub"], item["demo_offer"]["price_rub"]
            )

    def test_observed_price_is_only_a_title_matched_simulation(self):
        course = {
            **self.record,
            "kind": "course",
            "entity_key": None,
            "source_id": None,
            "title": "Курс «Учет для бизнеса» — обучение от Альфы",
            "source_url": "https://kurs.alfabank.ru/courses/test/",
        }
        self.write(course)
        observations = self.path / "prices.json"
        observations.write_text(
            json.dumps(
                {
                    "source": "https://kurs.alfabank.ru/",
                    "observed_at": "2026-11-15",
                    "courses": [
                        {"title": "Учет для бизнеса", "observed_price_rub": 3990}
                    ],
                }
            )
        )
        result = build(self.public, self.old, observations_path=observations)
        item = result["items"][0]
        self.assertEqual(item["price"]["status"], "unknown")
        self.assertEqual(item["demo_offer"]["price_rub"], 3990)
        self.assertEqual(
            item["demo_offer"]["reference"]["match_status"], "title_match_not_verified"
        )
        self.assertEqual(
            normalize_title("Курс «Учет для бизнеса», расширенный — обучение"),
            "учет для бизнеса расширенный",
        )
        self.assertNotEqual(
            normalize_title(course["title"]),
            normalize_title("Курс «Учет для бизнеса», расширенный — обучение"),
        )

    def test_invalid_price_reference_is_rejected(self):
        self.write(self.record)
        observations = self.path / "prices.json"
        for amount in (0, -1, True, "3000"):
            observations.write_text(
                json.dumps(
                    {
                        "source": "https://kurs.alfabank.ru/",
                        "observed_at": "2026-11-15",
                        "courses": [{"title": "Курс", "observed_price_rub": amount}],
                    }
                )
            )
            with (
                self.subTest(amount=amount),
                self.assertRaisesRegex(ValueError, "Invalid historical price"),
            ):
                build(self.public, self.old, observations_path=observations)

    def test_matching_course_title_is_candidate_not_verified_identity(self):
        course = {
            **self.record,
            "kind": "course",
            "entity_key": None,
            "source_id": None,
            "title": "Курс «Управление командой» — обучение от Альфы",
            "source_url": "https://kurs.alfabank.ru/courses/management/",
        }
        self.write(course)
        self.old.write_text(
            json.dumps(
                [
                    {
                        "entity_key": "course:1",
                        "kind": "course",
                        "title": "Управление командой",
                        "source_id": "1",
                    },
                    {
                        "entity_key": "course:2",
                        "kind": "course",
                        "title": "Уникальный курс",
                        "source_id": "2",
                    },
                ]
            )
        )
        result = build(self.public, self.old)
        item = result["items"][0]
        self.assertEqual(item["historical_title_candidate"], "course:1")
        self.assertFalse(item["historical_id_match"])
        self.assertIsNone(item["source_id"])
        self.assertEqual(
            sum(x["title"] == "Уникальный курс" for x in result["items"]), 1
        )
        self.assertEqual(
            result["audit"]["restored"]["course_title_candidates_unverified"], 1
        )


if __name__ == "__main__":
    unittest.main()
