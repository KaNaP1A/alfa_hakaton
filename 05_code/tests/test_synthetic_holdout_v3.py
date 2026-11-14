import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SyntheticSplitTests(unittest.TestCase):
    @unittest.skipUnless(
        (ROOT / "artifacts/relevance_v1/training/synthetic_queries.json").is_file(),
        "Historical synthetic training artifact is not included in Git",
    )
    def test_separate_catalogs_and_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "holdout"
            subprocess.run(
                [sys.executable, "scripts/build_synthetic_holdout_v3.py", "--output", str(output)],
                cwd=ROOT,
                env={"PYTHONPATH": str(ROOT / "src")},
                check=True,
                capture_output=True,
            )
            splits = {}
            for split in ("validation", "test"):
                queries = [
                    json.loads(s)
                    for s in (output / split / "queries.jsonl").read_text().splitlines()
                ]
                labels = [
                    json.loads(s)
                    for s in (output / split / "labels.jsonl").read_text().splitlines()
                ]
                docs = json.loads(
                    (output / split / "catalog/generation-synthetic/catalog.json").read_text()
                )
                keys = {d["entity_key"] for d in docs}
                self.assertEqual({x["id"] for x in queries}, {x["id"] for x in labels})
                self.assertTrue(
                    all(len(x["positive"]) == 2 and set(x["positive"]) <= keys for x in labels)
                )
                self.assertTrue(all(not any(k.startswith("oracle_") for k in d) for d in docs))
                splits[split] = (queries, keys)
            self.assertFalse(splits["validation"][1] & splits["test"][1])
            self.assertFalse(
                {x["family"] for x in splits["validation"][0]}
                & {x["family"] for x in splits["test"][0]}
            )
            self.assertFalse(
                {x["query"].casefold() for x in splits["validation"][0]}
                & {x["query"].casefold() for x in splits["test"][0]}
            )


if __name__ == "__main__":
    unittest.main()
