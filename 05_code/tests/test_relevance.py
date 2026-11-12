import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from test_suggestions import material, write_bundle

from alfa_reco.eligibility import candidate_support
from alfa_reco.retrieval import RankingConfig
from alfa_reco.search import SearchEngine


@unittest.skipUnless(importlib.util.find_spec("pymorphy3"), "Optional relevance morphology")
class QueryRepresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from alfa_reco.relevance_text import Morphology

        cls.morph = Morphology()

    def test_real_morphology_matches_inflections(self):
        self.assertEqual(self.morph.lemmas("сотрудниками договоров"), ["сотрудник", "договор"])
        self.assertEqual(self.morph.lemmas("работники"), self.morph.lemmas("работника"))

    def test_independent_goal_clauses_are_order_invariant(self):
        a = self.morph.query_view("Как выбрать поставщика и проверить договор поставки")
        b = self.morph.query_view("Как проверить договор поставки и выбрать поставщика")
        self.assertTrue(a["canonicalized"])
        self.assertEqual(a["semantic"], b["semantic"])

    def test_action_objects_cannot_be_swapped(self):
        a = self.morph.query_view("как продать магазин и купить оборудование")
        b = self.morph.query_view("как купить магазин и продать оборудование")
        self.assertNotEqual(a["semantic"], b["semantic"])

    def test_roles_direction_and_negation_remain_protected(self):
        for query in [
            "банк платит клиенту",
            "клиент платит банку",
            "перевод от клиента",
            "товар без маркировки",
            "не платить поставщику",
            "работа после регистрации",
        ]:
            self.assertFalse(self.morph.query_view(query)["canonicalized"], query)
        self.assertNotEqual(
            self.morph.query_view("банк кредитует магазин")["semantic"],
            self.morph.query_view("магазин кредитует банк")["semantic"],
        )


class SearchProfileTests(unittest.TestCase):
    def test_topic_selection_applies_one_bounded_boost_after_ml(self):
        with tempfile.TemporaryDirectory() as temp:
            write_bundle(
                temp,
                [
                    material("article:a", "Открыть кофейню: реклама", ["Маркетинг"]),
                    material("article:b", "Открыть кофейню: финансы", ["Финансы"]),
                ],
            )
            engine = SearchEngine(temp)

            class Backend:
                config = RankingConfig()
                policy = {"semantic_min": 0.84, "strong_semantic_min": 0.92, "lexical_min": 0.85}

                def result(self, query, allowed, selected):
                    dense = {"card": [0.9, 0.9], "body": [0, 0], "lesson": [0, 0]}
                    signals = engine.retriever.signals(query, dense, selected_keys=selected)
                    _, lexical, _, fused, ranks = engine.retriever.rank(
                        signals, self.config, allowed
                    )
                    return {
                        "view": {"normalization": "test", "canonicalized": True},
                        "signals": signals,
                        "dense": dense,
                        "ranked": [0, 1],
                        "lexical": lexical,
                        "fused": fused,
                        "ranks": ranks,
                        "model_scores": {0: 2, 1: 1},
                    }

                def support(self, prepared, i, selected=False, conflict=False):
                    return candidate_support(
                        "открыть кофейню",
                        engine.catalog[i],
                        0.9,
                        selected=selected,
                        conflict=conflict,
                    )

            engine._relevance = Backend()
            normal = engine.search("открыть кофейню", mode="relevance")
            self.assertEqual(normal["results"][0]["entity_key"], "article:a")
            option = next(
                row
                for row in engine.suggestions.entries.values()
                if row["kind"] == "topics" and row["label"] == "Финансы"
            )
            chosen = engine.search(
                "открыть кофейню",
                mode="relevance",
                selection_id=option["id"],
                selection_generation=engine.generation,
            )
            self.assertEqual(chosen["results"][0]["entity_key"], "article:b")
            self.assertAlmostEqual(
                chosen["results"][0]["scores"]["final_score"], 1.25 / 62, places=7
            )

    def test_new_profile_uses_its_own_scores_and_admission_without_old_encoder(self):
        with tempfile.TemporaryDirectory() as temp:
            write_bundle(
                temp,
                [material("article:a", "Договор аренды"), material("article:b", "Договор подряда")],
            )
            engine = SearchEngine(temp)

            class Backend:
                config = RankingConfig()
                policy = {"semantic_min": 0.84, "strong_semantic_min": 0.92, "lexical_min": 0.85}

                def result(self, query, allowed, selected):
                    dense = {"card": [0.9, 0.2], "body": [0, 0], "lesson": [0, 0]}
                    signals = engine.retriever.signals(query, dense)
                    ranked, lexical, _, fused, ranks = engine.retriever.rank(
                        signals, self.config, allowed
                    )
                    return {
                        "view": {"normalization": "test", "canonicalized": True},
                        "signals": signals,
                        "dense": dense,
                        "ranked": ranked,
                        "lexical": lexical,
                        "fused": fused,
                        "ranks": ranks,
                        "model_scores": {i: float(2 - i) for i in ranked},
                    }

                def support(self, prepared, i, selected=False, conflict=False):
                    return candidate_support(
                        "договор аренды",
                        engine.catalog[i],
                        prepared["dense"]["card"][i],
                        selected=selected,
                        conflict=conflict,
                    )

            engine._relevance = Backend()
            result = engine.search("договор аренды", mode="relevance")
            self.assertEqual(result["mode"], "relevance_experimental")
            self.assertTrue(result["model_trained"])
            self.assertEqual(result["results"][0]["entity_key"], "article:a")
            self.assertEqual(result["results"][0]["scores"]["final_score"], 2.0)
            self.assertIsNone(engine.encoder)


@unittest.skipUnless(
    importlib.util.find_spec("catboost") and importlib.util.find_spec("pymorphy3"),
    "Optional relevance training dependencies",
)
class PairSupervisionTests(unittest.TestCase):
    def test_manifest_source_reflects_selected_training_regime(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from train_relevance import training_source_for_regime

        self.assertEqual(
            training_source_for_regime("synthetic_only"),
            "weak_pairs_with_provisional_weight_scaling",
        )
        self.assertEqual(
            training_source_for_regime("provisional_only"), "provisional_assistant_only"
        )
        with self.assertRaises(ValueError):
            training_source_for_regime("unknown")

    def test_unknown_grades_stay_unknown_and_only_explicit_preferences_train(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from train_relevance import make_pool

        from alfa_reco.relevance import FEATURES

        groups = [
            {
                "features": [[1.0] * len(FEATURES), [0.0] * len(FEATURES)],
                "grades": [None, None],
                "pairs": [(0, 1)],
                "pair_weights": [1.0],
                "source": "synthetic",
            }
        ]
        # Add a known group so the relative weight normalization has a reference.
        groups.append({**groups[0], "grades": [3, 0], "source": "provisional_assistant"})
        pool = make_pool(groups, weak_scale=0.3)
        self.assertEqual(pool.num_pairs(), 2)
        self.assertEqual(groups[0]["grades"], [None, None])
        self.assertEqual(make_pool(groups, weak_scale=0).num_row(), 2)
        self.assertEqual(make_pool(groups, weak_scale=1, synthetic_only=True).num_row(), 2)


if __name__ == "__main__":
    unittest.main()
