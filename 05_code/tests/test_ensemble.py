import tempfile
import unittest
from dataclasses import asdict
from unittest.mock import patch

from test_suggestions import material, write_bundle

from alfa_reco.cli import atomic_json, sha256
from alfa_reco.ensemble import METHODS, fuse, validate_weights
from alfa_reco.retrieval import RankingConfig
from alfa_reco.search import SearchEngine


class FusionTests(unittest.TestCase):
    def test_weighted_fusion_accounts_for_rank_and_absent_items(self):
        lists = {
            "bm25": ["a", "b"],
            "hybrid": ["b", "c"],
            "catboost": ["b", "c"],
        }
        weights = {"bm25": 0.2, "hybrid": 0.3, "catboost": 0.5}
        score, parts = fuse(lists, weights)
        self.assertGreater(score["b"], score["a"])
        self.assertAlmostEqual(score["a"], 0.2)
        self.assertAlmostEqual(sum(parts["b"].values()), score["b"])
        self.assertNotIn("bm25", parts["c"])

    def test_invalid_weights_and_duplicate_results(self):
        for weights in [
            {"bm25": 1},
            dict.fromkeys(METHODS, -0.25),
            dict.fromkeys(METHODS, float("nan")),
            dict.fromkeys(METHODS, 0.2),
            {"bm25": True, "hybrid": 0, "catboost": 0},
        ]:
            with self.assertRaises(ValueError):
                validate_weights(weights)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            fuse({m: ["x", "x"] for m in METHODS}, dict.fromkeys(METHODS, 1 / 3))

    def test_disabled_component_does_not_inject_zero_score_candidates(self):
        scores, parts = fuse(
            {"bm25": ["a"], "hybrid": ["disabled"], "catboost": []},
            {"bm25": 1, "hybrid": 0, "catboost": 0},
        )
        self.assertEqual(set(scores), {"a"})
        self.assertEqual(parts["a"], {"bm25": 1.0})

    def test_ensemble_rejects_incompatible_models_and_exposes_contributions(self):
        with tempfile.TemporaryDirectory() as temp:
            catalog = [
                material("article:a", "Как открыть кофейню"),
                material("article:b", "Договор аренды"),
            ]
            path = write_bundle(temp, catalog)
            for name in ("catboost_small",):
                (path / (name + ".cbm")).write_bytes(name.encode())
            engine = SearchEngine(temp)
            engine.manifest["semantic"] = {"vectors_sha256": "unit-test"}
            engine.encoder = object()
            engine.dense_signals = lambda query: {
                "card": [0.9, 0.3],
                "body": [0.0, 0.0],
                "lesson": [0.0, 0.0],
            }
            config = {
                "catalog_sha256": engine.manifest["catalog_sha256"],
                "vectors_sha256": "unit-test",
                "model_sha256": sha256(path / "catboost_small.cbm"),
                "retrieval_parameters": asdict(RankingConfig()),
                "weights": dict.fromkeys(METHODS, 1 / 3),
            }
            atomic_json(path / "ensemble_config.json", config)

            def mock_model(mode, ranked, signals, config=None):
                return list(ranked), {i: float(i) for i in ranked}

            with patch.object(engine, "_model_order", side_effect=mock_model):
                result = engine.search("открыть кофейню", mode="ensemble")
                first = result["results"][0]
                self.assertEqual(first["entity_key"], "article:a")
                self.assertAlmostEqual(
                    first["scores"]["final_score"],
                    sum(first["ensemble_contributions"].values()),
                    places=5,
                )
                self.assertEqual(result["ensemble_weights"], dict.fromkeys(METHODS, 1 / 3))

                class Interpreter:
                    model = "gemma3:1b"

                    def model_digest(self):
                        return "model-digest"

                    def analyze(self, query):
                        return {
                            "status": "ok",
                            "object": "кофейню",
                            "negation_present": "не" in query.split(),
                        }

                engine.interpreter = Interpreter()
                config.update(llm_boost=0.2, llm_digest="model-digest", llm_model="gemma3:1b")
                atomic_json(path / "ensemble_config.json", config)
                boosted = engine.search("открыть кофейню", mode="ensemble")
                self.assertTrue(boosted["llm_ranking_applied"])
                self.assertGreater(
                    boosted["results"][0]["scores"]["final_score"],
                    first["scores"]["final_score"],
                )
                config["llm_digest"] = "different-model"
                atomic_json(path / "ensemble_config.json", config)
                mismatched = engine.search("открыть кофейню", mode="ensemble")
                self.assertFalse(mismatched["llm_ranking_applied"])
                self.assertEqual(mismatched["results"][0]["scores"], first["scores"])
                config["llm_digest"] = "model-digest"
                atomic_json(path / "ensemble_config.json", config)
                negated = engine.search("не кофейню", mode="ensemble")
                self.assertFalse(negated["llm_ranking_applied"])
                config["rrf_k"] = 10
                atomic_json(path / "ensemble_config.json", config)
                with self.assertRaisesRegex(ValueError, "fusion configuration"):
                    engine.search("кофейню", mode="ensemble")
                config.pop("rrf_k")
                # Old metadata without the newly explicit BM25 defaults stays compatible.
                config["retrieval_parameters"].pop("bm25_k1")
                config["retrieval_parameters"].pop("bm25_b")
                atomic_json(path / "ensemble_config.json", config)
                self.assertEqual(
                    engine._ensemble_weights()["weights"], dict.fromkeys(METHODS, 1 / 3)
                )
                (path / "catboost_small.cbm").write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "model"):
                    engine.search("кофейню", mode="ensemble")
