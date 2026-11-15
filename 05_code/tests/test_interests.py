import json
import tempfile
import unittest
from pathlib import Path

from alfa_reco.interests import interest_directory, load_interest_config


class InterestDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.json"
        self.config({})
        self.catalog = [
            {"entity_key": "article:1", "kind": "article", "topics": [" Старт   бизнеса ", "Финансы"], "tags": ["старт бизнеса", "Финансы"]},
            {"entity_key": "article:1", "kind": "article", "topics": ["Старт бизнеса"], "tags": []},
            {"entity_key": "course:2", "kind": "course", "topics": ["Старт бизнеса"], "tags": ["Авторская тема"]},
            {"entity_key": "article:3", "kind": "article", "topics": ["Законы"], "tags": [], "industries": ["Маркетинг"]},
            {"entity_key": "glossary:1", "kind": "glossary", "topics": ["Маркетинг"], "tags": ["Старт бизнеса"]},
        ]

    def config(self, categories):
        self.path.write_text(json.dumps({"version": 1, "categories": categories}), encoding="utf-8")

    def directory(self):
        return interest_directory(self.catalog, "g1", config_path=self.path)

    def test_counts_sources_normalization_and_exclusions(self):
        result = self.directory()
        self.assertEqual(result["generation"], "g1")
        self.assertEqual([c["id"] for c in result["categories"]], ["business", "finance"])
        business, finance = result["categories"]
        self.assertEqual(business["material_count"], 2)
        self.assertEqual(business["topics"], [{"value": "Старт бизнеса", "label": "Старт бизнеса", "sources": ["topics", "tags"], "material_count": 2}])
        self.assertEqual(finance["material_count"], 1)
        self.assertEqual([t["value"] for t in finance["topics"]], ["Финансы"])

    def test_explicit_mapping_only_when_present_and_stable_sort(self):
        self.config({"business": ["Авторская тема", "Отсутствующая"]})
        business = self.directory()["categories"][0]
        self.assertEqual([t["value"] for t in business["topics"]], ["Старт бизнеса", "Авторская тема"])
        self.assertEqual(business["topics"][1]["sources"], ["tags"])
        self.assertEqual(business["material_count"], 2)
        self.assertEqual(self.directory(), interest_directory(list(reversed(self.catalog)), "g1", config_path=self.path))

    def test_invalid_configuration_is_rejected(self):
        for categories in [
            {"unknown": ["тема"]}, {"business": "тема"},
            {"business": [" "]}, {"business": ["x" * 151]},
            {"business": ["Тема", " тема "]}, {"finance": ["Законы"]},
            {"business": ["Старт бизнеса"]}, {"business": [42]},
        ]:
            with self.subTest(categories=categories):
                self.config(categories)
                with self.assertRaises(ValueError):
                    load_interest_config(self.path)
        for data in ['{"version":1,"version":1,"categories":{}}', '{"version":true,"categories":{}}', '{}', 'not json']:
            self.path.write_text(data)
            with self.assertRaises(ValueError):
                load_interest_config(self.path)

    def test_multiple_facets_count_material_once(self):
        self.config({"business": ["Финансы"]})
        category = self.directory()["categories"][0]
        self.assertEqual(category["material_count"], 2)
        self.assertEqual([t["material_count"] for t in category["topics"]], [2, 1])


if __name__ == "__main__":
    unittest.main()
