import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from config.settings import Settings
from infrastructure.python_recommender import PythonRecommender
from infrastructure.recommender import UpstreamError


class PythonRecommenderTests(unittest.TestCase):
    def setUp(self):
        self.singleton = patch.object(PythonRecommender, "_instance", None)
        self.singleton.start()
        self.addCleanup(self.singleton.stop)
        self.engine = MagicMock(generation="test-v1")
        self.engine.search.return_value = {"generation": "test-v1", "results": []}
        self.engine.suggest.return_value = {"generation": "test-v1", "completions": []}
        self.factory = MagicMock(return_value=self.engine)
        self.module = patch(
            "infrastructure.python_recommender.import_module",
            return_value=SimpleNamespace(SearchEngine=self.factory),
        )
        self.module.start()
        self.addCleanup(self.module.stop)
        self.settings = Settings(reco_mode="python", reco_catalog="/tmp/test-catalog")

    def test_concurrent_construction_loads_once_and_close_keeps_model(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            instances = list(pool.map(lambda _: PythonRecommender(self.settings), range(20)))
        self.assertTrue(all(item is instances[0] for item in instances))
        self.factory.assert_called_once()
        self.engine.relevance_backend.assert_called_once()
        instances[0].close()
        self.assertIs(PythonRecommender(self.settings), instances[0])
        with self.assertRaises(ValueError):
            PythonRecommender(Settings(reco_mode="python", reco_catalog="/tmp/other-catalog"))

    def test_failed_initialization_can_retry(self):
        self.factory.side_effect = RuntimeError("Load failed")
        with self.assertRaises(RuntimeError):
            PythonRecommender(self.settings)
        self.assertIsNone(PythonRecommender._instance)
        self.factory.side_effect = None
        self.assertEqual(PythonRecommender(self.settings).health()["generation"], "test-v1")

    def test_direct_search_and_validation_errors(self):
        model = PythonRecommender(self.settings)
        model.search("coffee", 5, selection_id="chosen", clarification_token="token")
        self.assertEqual(self.engine.search.call_args.kwargs["mode"], "relevance")
        self.assertEqual(self.engine.search.call_args.kwargs["selection_id"], "chosen")
        model.suggest("coffee", 3)
        self.engine.suggest.assert_called_once_with("coffee", 3)
        self.engine.search.side_effect = ValueError("stale token")
        with self.assertRaises(UpstreamError) as error:
            model.search("coffee", 5)
        self.assertEqual(error.exception.status, 400)
        with self.assertRaises(UpstreamError):
            model.recommend("stale", [], [])
