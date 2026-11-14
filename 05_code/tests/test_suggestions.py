import tempfile
import unittest
from pathlib import Path

from alfa_reco.cli import atomic_json, clean, sha256
from alfa_reco.lessons import attach_lessons, parse_as_of
from alfa_reco.search import SearchEngine
from alfa_reco.storage import output_lock
from alfa_reco.suggestions import SuggestionIndex, build_index, one_edit


def material(key, title, topics=(), **extra):
    return {
        "entity_key": key,
        "source_id": key.split(":")[-1],
        "kind": key.split(":")[0],
        "title": title,
        "description": "",
        "topics": list(topics),
        "tags": [],
        "industries": [],
        "search_text": title + " " + " ".join(topics),
        "access_type": "open",
        "source_url": None,
        "canonical_url": None,
        "data_quality_flags": [],
        **extra,
    }


def lesson(key, **extra):
    return {
        "Id": key,
        "Title": "Удержание сотрудников",
        "Description": None,
        "IsGroup": "f",
        "IsDeleted": "f",
        **extra,
    }


def binding(key, **extra):
    return {
        "Id": "binding-" + key,
        "CourseId": "course",
        "LessonId": key,
        "IsClosed": "f",
        "IsDeleted": "f",
        "ClosedUntil": None,
        "IsTrial": "f",
        "ParentGroupId": None,
        **extra,
    }


def write_bundle(root, catalog):
    path = Path(root) / "generation-test"
    path.mkdir()
    atomic_json(path / "catalog.json", catalog)
    digest = sha256(path / "catalog.json")
    atomic_json(path / "suggestions.json", build_index(catalog, digest))
    atomic_json(
        path / "manifest.json",
        {
            "catalog_sha256": digest,
            "semantic": None,
            "suggestions": {"sha256": sha256(path / "suggestions.json")},
        },
    )
    atomic_json(Path(root) / "CURRENT.json", {"generation": path.name})
    return path


def enable_test_dense(engine):
    """Exercise hybrid integration without loading an embedding model in unit tests."""
    engine.dense_signals = lambda query: {
        source: [0.0] * len(engine.catalog) for source in ("card", "body", "lesson")
    }
    return engine


class LessonTests(unittest.TestCase):
    def attach(self, lessons, bindings, access="open", as_of=None):
        catalog = [material("course:course", "Управление", access_type=access)]
        report = attach_lessons(catalog, lessons, bindings, clean, as_of)
        return catalog[0].get("lessons", []), report

    def test_open_course_lesson_and_group(self):
        result, report = self.attach(
            [lesson("g", IsGroup="t"), lesson("l")],
            [binding("g"), binding("l", ParentGroupId="g", IsTrial="t")],
        )
        self.assertEqual([item["lesson_id"] for item in result], ["l"])
        self.assertFalse(result[0]["direct_access_verified"])
        self.assertEqual(report["group_or_unknown"], 1)

    def test_closed_deleted_unknown_and_missing_ancestor(self):
        for extra in [
            {"IsClosed": "t"},
            {"IsClosed": None},
            {"IsDeleted": "t"},
            {"ParentGroupId": "missing"},
            {"ClosedUntil": "garbage"},
        ]:
            with self.subTest(extra=extra):
                result, _ = self.attach(
                    [lesson("g", IsGroup="t"), lesson("l")],
                    [binding("g", **extra), binding("l", ParentGroupId="g")],
                )
                self.assertEqual(result, [])

    def test_cycle(self):
        result, report = self.attach(
            [lesson("g", IsGroup="t"), lesson("l")],
            [binding("g", ParentGroupId="g"), binding("l", ParentGroupId="g")],
        )
        self.assertEqual(result, [])
        self.assertEqual(report["ancestor_cycle"], 2)

    def test_scheduled_date_is_explicit_and_reproducible(self):
        b = binding("l", ClosedUntil="2026-01-01 00:00:00+00", IsTrial="t")
        for time in [None, parse_as_of("2025-01-01T00:00:00Z")]:
            self.assertEqual(self.attach([lesson("l")], [b], as_of=time)[0], [])
        self.assertEqual(
            len(self.attach([lesson("l")], [b], as_of=parse_as_of("2026-01-01T00:00:00Z"))[0]),
            1,
        )
        with self.assertRaises(ValueError):
            parse_as_of("2026-01-01")

    def test_paid_unknown_trial_and_duplicates(self):
        for access in ["open", "paid", "subscription", "unknown"]:
            self.assertEqual(self.attach([lesson("l")], [binding("l")], access)[0], [])
        self.assertEqual(len(self.attach([lesson("l")], [binding("l", IsTrial="t")], "paid")[0]), 1)
        self.assertEqual(len(self.attach([lesson("l")], [binding("l", IsTrial="t")], "unknown")[0]), 1)
        self.assertEqual(self.attach([lesson("l")], [binding("l"), binding("l")])[0], [])


class SuggestionTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [
            material("article:coffee", "Как открыть кофейню", ["Старт бизнеса"]),
            material("article:loyal", "Лояльность сотрудников", ["Управление командой"]),
            material("article:client", "Лояльность клиентов", ["Маркетинг"]),
            material("document:rent", "Договор аренды помещения", ["Документы"]),
        ]
        self.data = build_index(self.catalog, "digest")
        self.index = SuggestionIndex(self.data, self.catalog, "generation-test")

    def test_empty_short_and_unknown(self):
        for query in ["", " ", "к", "как мне", "!!!"]:
            self.assertEqual(self.index.suggest(query)["status"], "insufficient_input")
        for query in ["Frontend", "zzzxxyy"]:
            result = self.index.suggest(query)
            self.assertEqual(result["completions"], [])
            self.assertEqual(result["related_topics"], [])

    def test_partial_and_typo(self):
        for query in ["открыть коф", "КОФЕЙНЮ", "кофеня", "кофейнб"]:
            with self.subTest(query=query):
                result = self.index.suggest(query)
                self.assertIn(
                    "Как открыть кофейню",
                    [row["label"] for row in result["completions"]],
                )
        self.assertTrue(self.index.suggest("кофеня")["typo_tolerant_match"])
        self.assertIn(
            "Договор аренды помещения",
            [row["label"] for row in self.index.suggest("договор арнеды")["completions"]],
        )

    def test_context_does_not_drop_employee(self):
        result = self.index.suggest("повысить лояльность сотруд")
        labels = [row["label"] for row in result["completions"] + result["related_topics"]]
        self.assertIn("Лояльность сотрудников", labels)
        self.assertNotIn("Лояльность клиентов", labels)
        self.assertNotIn("Маркетинг", labels)

    def test_all_suggestions_have_evidence_and_stable_ids(self):
        self.assertEqual(self.data, build_index(list(reversed(self.catalog)), "digest"))
        for item in self.data["entries"]:
            self.assertTrue(item["entity_keys"])
            self.assertTrue(set(item["entity_keys"]) <= {row["entity_key"] for row in self.catalog})
        row = self.index.suggest("коф")["completions"][0]
        self.assertEqual(self.index.resolve(row["id"], "generation-test")["label"], row["label"])
        for identifier, generation in [(row["id"], "old"), ("fake", "generation-test")]:
            with self.assertRaises(ValueError):
                self.index.resolve(identifier, generation)

    def test_input_bounds(self):
        for query in ["a" * 301, "\n", None]:
            with self.assertRaises(ValueError):
                self.index.suggest(query)
        for limit in [0, 11]:
            with self.assertRaises(ValueError):
                self.index.suggest("коф", limit)

    def test_one_edit(self):
        for left, right in [("арнеда", "аренда"), ("кофен", "кофейн"), ("abc", "axc")]:
            self.assertTrue(one_edit(left, right))
        self.assertFalse(one_edit("кот", "сотрудник"))

    def test_search_keeps_query_and_adds_selection_recall(self):
        with tempfile.TemporaryDirectory() as root:
            write_bundle(root, self.catalog)
            engine = SearchEngine(root)
            with self.assertRaises(ValueError):
                engine.search("кофейню", mode="hybrid")
            enable_test_dense(engine)
            selection = engine.suggest("коф")["completions"][0]
            result = engine.search(
                "бизнес",
                mode="hybrid",
                selection_id=selection["id"],
                selection_generation=engine.generation,
            )
            self.assertEqual(result["query"], "бизнес")
            self.assertTrue(result["results"][0]["selection_match"])
            self.assertEqual(
                len(engine.search("кофейню", mode="hybrid", kind="document")["results"]),
                0,
            )
            with self.assertRaises(ValueError):
                engine.search("кофейню", mode="hybrid", selection_id="fake")

    def test_corrupt_or_stale_index_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = write_bundle(root, self.catalog)
            (path / "suggestions.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "hash"):
                SearchEngine(root)

    def test_writer_lock(self):
        with tempfile.TemporaryDirectory() as root, output_lock(root):
            with self.assertRaises(ValueError):
                with output_lock(root):
                    pass


class RankingArtifactTests(unittest.TestCase):
    def test_invalid_config_catalog_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = write_bundle(root, [material("article:a", "Как открыть кофейню")])
            atomic_json(
                path / "ranking_config.json", {"catalog_sha256": "different", "parameters": {}}
            )
            with self.assertRaisesRegex(ValueError, "different catalog"):
                SearchEngine(root)

    def test_small_ranker_schema_integrity_and_output(self):
        import importlib.util

        if (
            importlib.util.find_spec("catboost") is None
            or importlib.util.find_spec("numpy") is None
        ):
            self.skipTest("CatBoost and NumPy are optional test dependencies")
        import numpy as np
        from catboost import CatBoostRanker, Pool

        from alfa_reco.cli import sha256

        with tempfile.TemporaryDirectory() as root:
            catalog = [
                material("article:a", "Как открыть кофейню"),
                material("article:b", "Договор аренды"),
            ]
            path = write_bundle(root, catalog)
            names = [
                "bm25_title",
                "bm25_description",
                "cosine_card",
                "query_coverage",
                "title_coverage",
            ]
            model = CatBoostRanker(
                iterations=2,
                depth=2,
                loss_function="PairLogit",
                thread_count=1,
                verbose=False,
                allow_writing_files=False,
            )
            model.fit(
                Pool(
                    [[1, 0, 0.5, 1, 1], [0, 0, 0.1, 0, 0], [0, 0, 0.1, 0, 0], [1, 0, 0.5, 1, 1]],
                    [1, 0, 0, 1],
                    group_id=["a", "a", "b", "b"],
                    feature_names=names,
                )
            )
            model.save_model(str(path / "catboost_small.cbm"))
            atomic_json(
                path / "catboost_small_meta.json",
                {
                    "catalog_sha256": sha256(path / "catalog.json"),
                    "model_sha256": sha256(path / "catboost_small.cbm"),
                    "feature_names": names,
                    "vectors_sha256": "test-vectors",
                },
            )
            engine = SearchEngine(root)
            engine.manifest["semantic"] = {"vectors_sha256": "test-vectors"}

            class Encoder:
                def encode(self, query, normalize_embeddings=True):
                    return np.asarray([[1.0, 0.0]])

            engine.encoder = Encoder()
            engine.vectors = np.asarray([[1.0, 0.0], [0.0, 1.0]])
            result = engine.search("кофейню", mode="catboost")
            self.assertEqual(result["mode"], "catboost_experimental")
            self.assertTrue(result["model_trained"])
            self.assertEqual(result["results"][0]["entity_key"], "article:a")
            self.assertIsNotNone(result["results"][0]["scores"]["catboost"])
            from alfa_reco.retrieval import RankingConfig

            with self.assertRaisesRegex(ValueError, "retrain"):
                engine.search("кофейню", mode="catboost", ranking_config=RankingConfig(bm25_b=0))
            (path / "catboost_small.cbm").write_bytes(b"corrupted")
            with self.assertRaisesRegex(ValueError, "corrupt"):
                engine.search("кофейню", mode="catboost")
