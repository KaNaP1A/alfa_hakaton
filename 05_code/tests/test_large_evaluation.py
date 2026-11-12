import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

if importlib.util.find_spec("catboost") and importlib.util.find_spec("numpy"):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from large_experiment import build_queries, install_small, ranked_metrics
else:
    build_queries = None


@unittest.skipIf(build_queries is None, "Optional CatBoost/NumPy dependencies are not installed")
class LargeEvaluationTests(unittest.TestCase):
    def test_model_installation_checks_snapshot_and_records_training_parameters(self):
        from test_suggestions import material, write_bundle

        from alfa_reco.bundle import atomic_json, sha256
        from alfa_reco.search import SearchEngine

        class Ranker:
            def save_model(self, path):
                Path(path).write_bytes(b"test model artifact")

        with tempfile.TemporaryDirectory() as temp:
            path = write_bundle(temp, [material("article:a", "coffee")])
            manifest = json.loads((path / "manifest.json").read_text())
            manifest["semantic"] = {"vectors_sha256": "test-vectors"}
            atomic_json(path / "manifest.json", manifest)
            engine = SearchEngine(temp)
            install_small(temp, engine, Ranker(), ["bm25_title"], "test")
            meta = json.loads((path / "catboost_small_meta.json").read_text())
            self.assertEqual(meta["model_sha256"], sha256(path / "catboost_small.cbm"))
            self.assertEqual(meta["retrieval_parameters"]["bm25_k1"], 1.5)
            atomic_json(
                path / "ranking_config.json",
                {"catalog_sha256": manifest["catalog_sha256"], "parameters": {"bm25_b": 0}},
            )
            with self.assertRaisesRegex(ValueError, "changed during training"):
                install_small(temp, engine, Ranker(), ["bm25_title"], "test")

    def test_sources_for_one_item_never_cross_splits_and_exclusions_apply(self):
        catalog = [
            {
                "entity_key": "article:a",
                "title": "Как открыть небольшую кофейню",
                "kind": "article",
                "description": "Рассмотрим полезные практические шаги для предпринимателя",
            },
            {
                "entity_key": "article:b",
                "title": "Как открыть небольшую кофейню",
                "kind": "article",
                "description": "Дублирующееся название следует исключить полностью",
            },
            {
                "entity_key": "article:c",
                "title": "Договор аренды нежилого помещения",
                "kind": "article",
                "description": "Длительный срок соглашения обязан учитывать многие нюансы",
            },
        ]
        rows = build_queries(catalog, {"article:c"})
        self.assertEqual({row["target"] for row in rows}, {"article:a"})
        self.assertEqual(len({row["split"] for row in rows}), 1)
        self.assertEqual(len({row["query"] for row in rows}), len(rows))
        self.assertEqual(
            {row["source"] for row in rows}, {"title_fragment", "description_without_title_words"}
        )

    def test_candidate_recall_is_distinct_from_ranking(self):
        queries = [
            {"target": "a", "kind": "article", "source": "title_fragment"},
            {"target": "b", "kind": "course", "source": "title_fragment"},
        ]
        result = ranked_metrics(queries, [[1, 0], [0]], [["a", "x"], ["z"]])
        self.assertEqual(result["candidate_recall"], 0.5)
        self.assertEqual(result["mrr_at_10"], 0.25)


if __name__ == "__main__":
    unittest.main()
