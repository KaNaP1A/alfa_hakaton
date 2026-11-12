import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_synthetic  # noqa: E402
from smoke_synthetic_search import choose_sample  # noqa: E402


class SyntheticCliTests(unittest.TestCase):
    def test_smoke_sample_is_balanced_and_excludes_unjudged_or_autocomplete(self):
        rows = [
            {
                "query_id": f"{scenario}-{i}",
                "scenario": scenario,
                "task": "search",
                "source_id": "a",
            }
            for scenario, count in (("a", 9), ("b", 2))
            for i in range(count)
        ]
        rows.extend(
            [
                {"query_id": "unknown", "scenario": "a", "task": "search", "source_id": None},
                {"query_id": "prefix", "scenario": "a", "task": "autocomplete", "source_id": "a"},
            ]
        )
        selected = choose_sample(rows, 4, 42)
        self.assertEqual(choose_sample(rows, 4, 42), selected)
        self.assertEqual([row["scenario"] for row in selected].count("a"), 2)
        self.assertEqual([row["scenario"] for row in selected].count("b"), 2)
        self.assertTrue(all(row["source_id"] and row["task"] == "search" for row in selected))

    def test_writes_reproducible_and_refuses_to_replace_existing_output(self):
        catalog = [{"entity_key": "article:a", "title": "Как открыть кофейню", "kind": "article"}]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            protected = root / "protected.json"
            protected.write_text('{"queries": []}', encoding="utf-8")
            bundle = (root, {"catalog_sha256": "test-catalog"}, catalog)
            with (
                patch.object(generate_synthetic, "PROTECTED", [protected]),
                patch.object(generate_synthetic, "load_bundle", return_value=bundle),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                for name in ("one", "two"):
                    with patch.object(
                        sys, "argv", ["generate_synthetic", "--output", str(root / name)]
                    ):
                        generate_synthetic.main()
                self.assertEqual(
                    (root / "one/queries.jsonl").read_bytes(),
                    (root / "two/queries.jsonl").read_bytes(),
                )
                self.assertEqual(
                    (root / "one/review.jsonl").read_bytes(),
                    (root / "two/review.jsonl").read_bytes(),
                )
                review = json.loads((root / "one/review.jsonl").read_text().splitlines()[0])
                self.assertIn("human_review", review)
                before = (root / "one/queries.jsonl").read_bytes()
                with self.assertRaises(SystemExit):
                    with patch.object(
                        sys, "argv", ["generate_synthetic", "--output", str(root / "one")]
                    ):
                        generate_synthetic.main()
                self.assertEqual(before, (root / "one/queries.jsonl").read_bytes())


if __name__ == "__main__":
    unittest.main()
