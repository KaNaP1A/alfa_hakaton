import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from compare_score_fusions import evaluate, grid, normalize  # noqa: E402


class FusionEvaluationTests(unittest.TestCase):
    def test_grid_covers_every_nonempty_component_set(self):
        weights = grid()
        self.assertEqual(len(weights), 286)
        self.assertTrue(all(abs(sum(w) - 1) < 1e-12 and min(w) >= 0 for w in weights))
        self.assertEqual(len({tuple(i for i, value in enumerate(w) if value) for w in weights}), 15)

    def test_constant_score_and_known_order(self):
        np.testing.assert_array_equal(normalize(np.array([4.0, 4.0])), [0, 0])
        rows = [
            {
                "keys": ["a", "b"],
                "values": np.array([[0, 0, 0, 0], [1, 0, 0, 0]]),
                "labels": {"a": 3, "b": 0},
                "family": "one",
                "split": "test",
            }
        ]
        metric = evaluate(rows, (1, 0, 0, 0))["test"]
        self.assertAlmostEqual(metric["mrr5_pooled"], 0.5)
        self.assertAlmostEqual(metric["precision5_pooled"], 0.2)
        self.assertLess(metric["ndcg5_pooled"], 1)


if __name__ == "__main__":
    unittest.main()
