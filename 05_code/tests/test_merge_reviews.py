import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from merge_reviews import merge  # noqa: E402


class MergeReviewTests(unittest.TestCase):
    def setUp(self):
        self.a = [
            {
                "query_id": "q",
                "entity_key": "a",
                "reviewer_a": 3,
                "reviewer_b": None,
                "adjudicated": None,
            }
        ]
        self.b = [
            {
                "query_id": "q",
                "entity_key": "a",
                "reviewer_a": None,
                "reviewer_b": 2,
                "adjudicated": None,
            }
        ]

    def test_merges_without_inventing_resolution(self):
        self.assertEqual(merge(self.a, self.b)[0]["reviewer_a"], 3)
        self.assertEqual(merge(self.a, self.b)[0]["reviewer_b"], 2)
        self.assertIsNone(merge(self.a, self.b)[0]["adjudicated"])

    def test_rejects_invalid_and_non_independent_data(self):
        with self.assertRaises(ValueError):
            merge(self.a, [])
        with self.assertRaises(ValueError):
            merge(self.a, self.b + self.b)
        with self.assertRaises(ValueError):
            merge(self.a, [{**self.b[0], "reviewer_a": 3}])
        with self.assertRaises(ValueError):
            merge([{**self.a[0], "reviewer_a": 4}], self.b)

    def test_merge_does_not_drop_unblinding_metadata(self):
        with self.assertRaisesRegex(ValueError, "blinded"):
            merge([{**self.a[0], "automatic_hint_seen": True}], self.b)


if __name__ == "__main__":
    unittest.main()
