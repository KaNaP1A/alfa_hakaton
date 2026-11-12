import unittest

from alfa_reco.evaluation import evaluate_pool, metric_at_5, resolved_grade


class AnnotationTests(unittest.TestCase):
    def setUp(self):
        self.pool = [
            {
                "query_id": "q",
                "family": "family",
                "split": "test",
                "query": "пример",
                "candidates": [{"entity_key": "a"}, {"entity_key": "b"}],
            }
        ]
        self.rankings = [{"query_id": "q", "rankings": {"bm25": ["a", "b"], "hybrid": ["b", "a"]}}]
        self.judgments = [
            {
                "query_id": "q",
                "entity_key": key,
                "reviewer_a": None,
                "reviewer_b": None,
                "adjudicated": None,
            }
            for key in ("a", "b")
        ]

    def test_unjudged_results_do_not_turn_into_negative_labels(self):
        report = evaluate_pool(self.pool, self.rankings, self.judgments)
        self.assertEqual(report["pending_queries"], 1)
        self.assertEqual(report["completed_queries"], 0)
        self.assertEqual(report["metrics_by_split_and_method"], {})

    def test_two_assessors_and_disagreement(self):
        self.judgments[0].update(reviewer_a=3, reviewer_b=3)
        self.judgments[1].update(reviewer_a=2, reviewer_b=0)
        self.assertEqual(
            evaluate_pool(self.pool, self.rankings, self.judgments)["unresolved_disagreements"], 1
        )
        self.judgments[1]["adjudicated"] = 0
        report = evaluate_pool(self.pool, self.rankings, self.judgments)
        self.assertEqual(report["completed_queries"], 1)
        self.assertEqual(report["metrics_by_split_and_method"]["test"]["bm25"]["mrr5"], 1)
        self.assertEqual(report["metrics_by_split_and_method"]["test"]["hybrid"]["mrr5"], 0.5)
        self.assertEqual(metric_at_5(["a", "b"], {"a": 3, "b": 0})["precision5"], 0.2)

    def test_invalid_or_duplicate_labels_are_rejected(self):
        with self.assertRaises(ValueError):
            resolved_grade({"reviewer_a": True})
        with self.assertRaises(ValueError):
            evaluate_pool(self.pool, self.rankings, self.judgments + self.judgments)
        with self.assertRaises(ValueError):
            evaluate_pool(self.pool, self.rankings, self.judgments[:1])

    def test_automatic_and_unblinded_ratings_are_rejected(self):
        for metadata in [
            {"automatic_hint_seen": True},
            {"human_verified": False},
            {"assessor": "local_model_draft"},
        ]:
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                resolved_grade({"reviewer_a": 3, "reviewer_b": 3, **metadata})


if __name__ == "__main__":
    unittest.main()
