import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.import_adjudications import import_adjudications


class AdjudicationTests(unittest.TestCase):
    def test_import_preserves_votes_and_does_not_guess_blanks(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            pool = [
                {
                    "query_id": "q",
                    "query": "Задача",
                    "candidates": [
                        {"entity_key": "article:1", "title": "Статья", "description": "Описание"},
                        {"entity_key": "article:2", "title": "Другая", "description": "Текст"},
                    ],
                }
            ]
            (p / "pool.jsonl").write_text(json.dumps(pool[0], ensure_ascii=False) + "\n")
            (p / "rankings.jsonl").write_text("{}\n")
            hashes = {
                x: hashlib.sha256((p / x).read_bytes()).hexdigest()
                for x in ("pool.jsonl", "rankings.jsonl")
            }
            (p / "manifest.json").write_text(json.dumps({"hashes_before_review": hashes}))
            merged = [
                {
                    "query_id": "q",
                    "entity_key": "article:1",
                    "reviewer_a": 0,
                    "reviewer_b": 2,
                    "adjudicated": None,
                },
                {
                    "query_id": "q",
                    "entity_key": "article:2",
                    "reviewer_a": 3,
                    "reviewer_b": None,
                    "adjudicated": None,
                },
            ]
            (p / "merged").write_text("".join(json.dumps(x) + "\n" for x in merged))
            sheets = [
                {
                    "query_id": "q",
                    "entity_key": "article:1",
                    "query": "Задача",
                    "title": "Статья",
                    "description": "Описание",
                    "reviewer_a": "0",
                    "reviewer_b": "2",
                    "adjudicated": "1",
                },
                {
                    "query_id": "q",
                    "entity_key": "article:2",
                    "query": "Задача",
                    "title": "Другая",
                    "description": "Текст",
                    "reviewer_a": "3",
                    "reviewer_b": "",
                    "adjudicated": "",
                },
            ]
            with patch("scripts.import_adjudications.xlsx_rows", return_value=sheets):
                self.assertEqual(
                    import_adjudications(p, p / "merged", p / "input.xlsx", p / "out"), (1, 1)
                )
            result = [json.loads(x) for x in (p / "out").read_text().splitlines()]
            self.assertEqual(result[0]["adjudicated"], 1)
            self.assertEqual((result[0]["reviewer_a"], result[0]["reviewer_b"]), (0, 2))
            self.assertIsNone(result[1]["adjudicated"])
            sheets[0]["reviewer_a"] = "2"
            with patch("scripts.import_adjudications.xlsx_rows", return_value=sheets):
                with self.assertRaisesRegex(ValueError, "Original reviewer"):
                    import_adjudications(p, p / "merged", p / "input.xlsx", p / "out2")
