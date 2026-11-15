import json
import tempfile
import unittest
from pathlib import Path

from demo_catalog.build_catalog import build


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.public = self.path / "public.jsonl"
        self.old = self.path / "old.json"
        self.old.write_text(json.dumps([{"entity_key": "article:1", "kind": "article"}]))
        self.record = {"kind": "article", "entity_key": "article:1", "source_id": "1",
                       "source_url": "https://kurs.alfabank.ru/articles/a/", "title": "Тема\u2028тест",
                       "description": "текст", "observed_at": "2026-11-15", "price_raw_meta": "999"}

    def write(self, *rows):
        self.public.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n")

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
        self.assertEqual(result["audit"]["synthetic"], 12)
        for item in result["items"][1:]:
            self.assertEqual(item["origin"], "synthetic")
            self.assertIsNone(item["source_url"])
            self.assertIn(item["price"]["status"], {"fictional", "fictional_free"})

    def test_unverified_course_and_noindex(self):
        course = {**self.record, "kind": "course", "entity_key": None, "source_id": None,
                  "source_url": "https://kurs.alfabank.ru/courses/test/"}
        hidden = {**self.record, "source_url": "https://kurs.alfabank.ru/articles/hidden/", "source_noindex_raw": True}
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


if __name__ == "__main__":
    unittest.main()
