import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_synthetic import audit_rows  # noqa: E402

from alfa_reco.synthetic import build_dataset, normalize


class AuditSyntheticTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [
            {"entity_key": "a", "title": "Как открыть кофейню", "kind": "article"},
            {"entity_key": "b", "title": "Договор аренды помещения", "kind": "document"},
        ]
        self.rows, _ = build_dataset(self.catalog)

    def test_valid_dataset_passes(self):
        report = audit_rows(self.rows, self.catalog)
        self.assertTrue(report["passed_structural_checks"])
        self.assertEqual(report["errors"], {})

    def test_rejects_invented_relevance_and_unknown_source(self):
        row = {**self.rows[0], "relevance": 3, "source_id": "missing"}
        report = audit_rows([row], self.catalog)
        self.assertFalse(report["passed_structural_checks"])
        self.assertIn("unverified_relevance_as_truth", report["errors"])
        self.assertIn("unknown_source_id", report["errors"])

    def test_identical_queries_in_different_splits_are_detected(self):
        first = next(row for row in self.rows if row["source_id"])
        second = {
            **first,
            "query_id": "different",
            "split": "test" if first["split"] != "test" else "train",
        }
        report = audit_rows([first, second], self.catalog)
        self.assertIn("query_cross_split", report["errors"])
        self.assertIn("source_cross_split", report["errors"])
        self.assertIn("group_cross_split", report["errors"])

    def test_protected_items_and_queries_are_detected(self):
        row = next(row for row in self.rows if row["source_id"] == "a")
        report = audit_rows(
            [row],
            self.catalog,
            {"a"},
            {normalize("Как открыть кофейню")},
            {normalize(row["query"])},
        )
        self.assertEqual(report["errors"]["protected_source_overlap"], 1)
        self.assertEqual(report["errors"]["protected_title_overlap"], 1)
        self.assertEqual(report["errors"]["protected_query_overlap"], 1)


if __name__ == "__main__":
    unittest.main()
