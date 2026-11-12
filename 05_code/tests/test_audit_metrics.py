import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_ranking import family_average, pooled_metrics, stability, validate_cases


class AuditMetricTests(unittest.TestCase):
    def test_ideal_order_and_incomplete_judgments_are_explicit(self):
        labels = {"a": 3, "b": 2, "c": 0}
        self.assertEqual(pooled_metrics(["a", "b"], labels)["ndcg5_pooled"], 1)
        score = pooled_metrics(["unknown", "b", "a"], labels)
        self.assertEqual(score["judged5"], 0.4)
        self.assertEqual(score["mrr5_pooled"], 0.5)
        self.assertEqual(score["precision5_pooled"], 0.4)
        self.assertEqual(score["recall5_judged"], 1)
        self.assertIsNone(pooled_metrics(["c"], {"c": 0})["ndcg5_pooled"])

    def test_family_macro_does_not_reward_more_paraphrases(self):
        rows = [{"family": "a", "metrics": {"score": 1}}] * 10
        rows.append({"family": "b", "metrics": {"score": 0}})
        self.assertEqual(family_average(rows)["score"], 0.5)

    def test_empty_agreement_is_separate_from_retrieval_stability(self):
        empty = stability([], [])
        self.assertTrue(empty["both_empty"])
        self.assertIsNone(empty["jaccard5"])
        self.assertFalse(empty["top1_equal_nonempty"])
        nonempty = stability(["a", "b"], ["b", "a"])
        self.assertEqual(nonempty["jaccard5"], 1)
        self.assertFalse(nonempty["exact_order"])

    def test_family_and_exact_query_leakage_are_rejected(self):
        first = {
            "id": "a",
            "query": "налоги ИП",
            "family": "tax",
            "split": "val",
            "judgments": [{"entity_key": "a", "grade": 3}],
        }
        second = {**first, "id": "b", "split": "test"}
        with self.assertRaisesRegex(ValueError, "Family"):
            validate_cases([first, second], [{"entity_key": "a"}])
        second["family"] = "different"
        with self.assertRaisesRegex(ValueError, "Identical query"):
            validate_cases([first, second], [{"entity_key": "a"}])


if __name__ == "__main__":
    unittest.main()
