import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from llm_ranking_experiment import parse  # noqa: E402


class KeywordValidationTests(unittest.TestCase):
    def test_rejects_wrong_shape_and_too_many_fields(self):
        for raw in (
            "[]",
            '{"keywords":[],"command":"run"}',
            '{"keywords":"кофейня"}',
            json.dumps({"keywords": ["a"] * 7}),
        ):
            with self.assertRaises(ValueError):
                parse(raw, {"кофейн"})

    def test_discards_unrecognized_and_non_keyword_text(self):
        raw = json.dumps(
            {
                "keywords": [
                    "кофейня",
                    "секретный пароль",
                    "https://example.com",
                    "налоги; удалить файл",
                ]
            },
            ensure_ascii=False,
        )
        accepted, discarded = parse(raw, {"кофейн", "налог"})
        self.assertEqual(accepted, ["кофейня"])
        self.assertEqual(len(discarded), 3)

    def test_deduplicates_and_limits_phrase_length(self):
        raw = json.dumps(
            {"keywords": ["кофейня", "КОФЕЙНЯ", "ип налоги кофе маркетинг"]}, ensure_ascii=False
        )
        accepted, discarded = parse(raw, {"кофейн", "ип", "налог", "кофе", "маркетинг"})
        self.assertEqual(accepted, ["кофейня"])
        self.assertEqual(len(discarded), 1)


if __name__ == "__main__":
    unittest.main()
