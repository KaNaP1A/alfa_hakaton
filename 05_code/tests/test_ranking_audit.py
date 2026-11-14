import itertools
import math
import random
import tempfile
import unittest
from collections import Counter
from dataclasses import asdict

from test_suggestions import enable_test_dense, material, write_bundle

from alfa_reco.cli import atomic_json
from alfa_reco.eligibility import candidate_support
from alfa_reco.query_rules import plan_query
from alfa_reco.retrieval import BM25Index, FieldRetriever, RankingConfig
from alfa_reco.search import SearchEngine
from alfa_reco.text import embedding_query, tokens


class BM25MathematicsTests(unittest.TestCase):
    def test_matches_independent_formula_across_parameters(self):
        texts = ["налог налог ип", "налог учет отчет бизнес", "", "coffee cafe coffee"]
        query = "налог ип coffee нетвсловаре"
        documents = [Counter(tokens(t)) for t in texts]
        average = sum(sum(d.values()) for d in documents) / len(documents)
        for k1, b in itertools.product([0.1, 0.8, 1.5, 3.0], [0.0, 0.25, 0.75, 1.0]):
            actual = BM25Index(texts, k1, b).score(query)
            for doc, score in zip(documents, actual, strict=True):
                expected = 0.0
                for term in sorted(set(tokens(query))):
                    tf = doc[term]
                    if not tf:
                        continue
                    df = sum(term in d for d in documents)
                    idf = math.log(1 + (len(documents) - df + 0.5) / (df + 0.5))
                    expected += (
                        idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * sum(doc.values()) / average))
                    )
                self.assertAlmostEqual(score, expected, places=13)

    def test_saturation_and_length_normalization_have_expected_direction(self):
        texts = ["coffee", "coffee coffee", "coffee " + "other " * 100]
        scores = BM25Index(texts, b=0).score("coffee")
        self.assertGreater(scores[1], scores[0])
        self.assertLess(scores[1], 2 * scores[0])
        self.assertEqual(scores[0], scores[2])
        normalized = BM25Index(texts, b=1).score("coffee")
        self.assertGreater(normalized[0], normalized[2])

    def test_empty_unknown_and_repeated_query_terms(self):
        self.assertEqual(BM25Index([]).score("tax"), [])
        self.assertEqual(BM25Index(["", ""]).score("tax"), [0, 0])
        index = BM25Index(["налог ип", "договор аренды"])
        self.assertEqual(index.score("и в для"), [0, 0])
        self.assertEqual(index.score("квазинесуществующееслово"), [0, 0])
        self.assertEqual(index.score("налог налог ип"), index.score("ип налог"))

    def test_invalid_parameters_rejected_in_index_and_runtime_config(self):
        for k1, b in [
            (0, 0.75),
            (-1, 0.5),
            (1, -0.1),
            (1, 1.1),
            (float("nan"), 0.5),
            (1, float("inf")),
            (True, 0.5),
            (1, False),
        ]:
            with self.subTest(k1=k1, b=b):
                with self.assertRaises(ValueError):
                    BM25Index(["x"], k1, b)
                with self.assertRaises(ValueError):
                    RankingConfig(bm25_k1=k1, bm25_b=b)
        for params in [{"title": True}, {"candidate_count": True}, {"rrf_k": 2.5}]:
            with self.assertRaises(ValueError):
                RankingConfig(**params)

    def test_large_multidomain_corpus_invariants(self):
        rng = random.Random(42)
        vocabulary = tokens(
            "налоги маркетинг сотрудник договор медицина физика нейросети coffee python"
        )
        texts = [" ".join(rng.choices(vocabulary, k=5 + i % 80)) for i in range(5000)]
        index = BM25Index(texts)
        for _ in range(25):
            terms = rng.sample(vocabulary, 4)
            scores = index.score(" ".join(terms))
            rng.shuffle(terms)
            self.assertEqual(scores, index.score(" ".join(terms)))
            self.assertTrue(all(math.isfinite(score) and score >= 0 for score in scores))


class RankingRuntimeTests(unittest.TestCase):
    def test_parameters_reach_actual_field_scores(self):
        catalog = [
            material("article:a", "coffee"),
            material("article:b", "coffee " + "other " * 30),
        ]
        retriever = FieldRetriever(catalog)
        scores = retriever.signals("coffee", config=RankingConfig(bm25_b=0))["fields"]["title"]
        self.assertEqual(scores[0], scores[1])
        normalized = retriever.signals("coffee", config=RankingConfig(bm25_b=1))["fields"]["title"]
        self.assertGreater(normalized[0], normalized[1])

    def test_missing_dense_channel_cannot_inject_arbitrary_candidates(self):
        retriever = FieldRetriever([material("article:a", "tax"), material("article:b", "coffee")])
        signals = retriever.signals("unknown")
        self.assertEqual(retriever.rank(signals, RankingConfig(), semantic=True)[0], [])

    def test_persisted_config_loads_once_and_checks_catalog(self):
        with tempfile.TemporaryDirectory() as temp:
            path = write_bundle(temp, [material("article:a", "coffee")])
            engine = SearchEngine(temp)
            config = RankingConfig(bm25_b=0.25, bm25_k1=0.8)
            atomic_json(
                path / "ranking_config.json",
                {"catalog_sha256": engine.manifest["catalog_sha256"], "parameters": asdict(config)},
            )
            configured = enable_test_dense(SearchEngine(temp))
            self.assertEqual(configured.ranking_config, config)
            self.assertNotEqual(engine.ranking_config, config)
            result = configured.search("coffee", mode="hybrid")
            self.assertIsInstance(result["results"][0]["scores"]["final_score"], float)
            atomic_json(path / "ranking_config.json", {"catalog_sha256": "other", "parameters": {}})
            with self.assertRaisesRegex(ValueError, "different catalog"):
                SearchEngine(temp)

    def test_equivalent_staff_phrases_match_end_to_end(self):
        with tempfile.TemporaryDirectory() as temp:
            write_bundle(
                temp,
                [
                    material("article:a", "Управление сотрудниками"),
                    material("article:b", "Бухгалтерия"),
                ],
            )
            engine = enable_test_dense(SearchEngine(temp))
            first = engine.search("управление персоналом", mode="hybrid")
            second = engine.search("управление сотрудниками", mode="hybrid")
            self.assertEqual(
                [r["entity_key"] for r in first["results"]],
                [r["entity_key"] for r in second["results"]],
            )
            self.assertTrue(first["results"])
            self.assertEqual(first["query"], "управление персоналом")
            self.assertTrue(first["query_rules"]["synonym_rules"])

    def test_negation_and_direction_do_not_get_canonicalized_as_bags(self):
        for query in [
            "перевод от клиента",
            "не платить поставщику",
            "долг перед поставщиком",
            "клиенты вместо сотрудников",
        ]:
            self.assertEqual(embedding_query(query), query)
        self.assertEqual(plan_query("удержания из зарплаты сотрудников").retention_expansion, False)
        self.assertNotEqual(
            plan_query("взыскать долг с клиента").debt_expansion,
            plan_query("погасить долг поставщику").debt_expansion,
        )
        self.assertFalse(
            candidate_support("банк платит клиенту", material("article:a", "клиенту платит банк"))[
                "exact_title"
            ]
        )

    def test_api_counts_are_integers_and_synonyms_are_scoped(self):
        with tempfile.TemporaryDirectory() as temp:
            write_bundle(temp, [material("article:a", "coffee")])
            engine = enable_test_dense(SearchEngine(temp))
            for top in [True, 1.5, "5"]:
                with self.assertRaises(ValueError):
                    engine.search("coffee", mode="hybrid", top=top)
        for query in [
            "зарплата персонала",
            "неуправление персоналом",
            "управление персоналометрия",
        ]:
            self.assertFalse(plan_query(query).synonym_rules)

    def test_sentence_punctuation_preserves_results_and_technical_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            write_bundle(
                temp,
                [material("article:a", "Договор аренды"), material("article:b", "Договор подряда")],
            )
            engine = enable_test_dense(SearchEngine(temp))
            first = engine.search("договор аренды", mode="hybrid")
            second = engine.search("договор аренды.", mode="hybrid")
            self.assertEqual(first["results"], second["results"])
            self.assertEqual(second["query"], "договор аренды.")
        self.assertEqual(plan_query(".NET.").retrieval_query, ".NET")


if __name__ == "__main__":
    unittest.main()
