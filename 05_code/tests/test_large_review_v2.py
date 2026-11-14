import collections
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_large_review_v2 import build, scenarios


class LargeReviewTests(unittest.TestCase):
    def setUp(self):
        self.source = Path("evaluation/query_goals_v2.json")
        if not self.source.is_file():
            # The real evaluation pool may be withheld from public checkouts.
            temporary = tempfile.TemporaryDirectory()
            self.addCleanup(temporary.cleanup)
            self.source = Path(temporary.name) / "synthetic_goals.json"
            goals = {
                f"test_area_{area}": [f"решить тестовую задачу {area} вариант {item}" for item in range(10)]
                for area in range(12)
            }
            self.source.write_text(json.dumps(goals, ensure_ascii=False), encoding="utf-8")

    def test_reproducible_splits_keep_paraphrases_together(self):
        source = self.source
        rows = scenarios(source)
        self.assertEqual(rows, scenarios(source))
        self.assertEqual(len(rows), 360)
        self.assertEqual(
            collections.Counter(r["split"] for r in rows),
            {"train": 216, "validation": 72, "test": 72},
        )
        families = collections.defaultdict(set)
        for row in rows:
            families[row["family"]].add(row["split"])
        self.assertEqual(len(families), 120)
        self.assertTrue(all(len(splits) == 1 for splits in families.values()))

    def test_provisional_test_is_not_passed_to_search(self):
        source = self.source
        test_queries = {r["query"] for r in scenarios(source) if r["split"] == "test"}
        calls = []
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "manifest.json").write_text("{}")

            class Backend:
                model = object()
                path = root

                def prepare(self, *args, **kwargs):
                    return None

            class Engine:
                generation = "test-generation"
                manifest = {"catalog_sha256": "test-hash"}
                catalog = [
                    {
                        "entity_key": "article:x",
                        "title": "Материал",
                        "description": "Описание",
                        "kind": "article",
                    }
                ]

                def __init__(self, *args, **kwargs):
                    self.backend = Backend()

                def relevance_backend(self):
                    return self.backend

                def search(self, query, **kwargs):
                    calls.append(query)
                    return {"results": [], "alternatives": []}

            with patch("scripts.build_large_review_v2.SearchEngine", Engine):
                report = build(source, root / "output", 20261113)
            self.assertEqual(len(calls), 288 * 2)
            self.assertFalse(test_queries.intersection(calls))
            self.assertFalse(report["holdout_rankings_created"])
            holdout = [
                json.loads(line)
                for line in (root / "output/test_queries_unscored.jsonl").read_text().splitlines()
            ]
            self.assertEqual(len(holdout), 72)
