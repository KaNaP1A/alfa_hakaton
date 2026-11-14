import http.client
import json
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode

from test_suggestions import enable_test_dense, material, write_bundle

from alfa_reco.search import SearchEngine
from alfa_reco.server import make_server, serve


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        write_bundle(
            cls.temp.name, [material("article:1", "Как открыть кофейню", ["Старт бизнеса"],
                                     article_type_available=True)]
        )
        cls.engine = enable_test_dense(SearchEngine(cls.temp.name))
        cls.server = make_server(cls.engine, 0, default_mode="hybrid")
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def request(self, path, params=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(
                "GET", path + ("?" + urlencode(params) if params else ""), headers=headers or {}
            )
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_configured_search_returns_material(self):
        status, result = self.request("/search", {"q": "кофейню"})
        self.assertEqual(status, 200)
        self.assertEqual(result["mode"], "hybrid_rrf")
        self.assertEqual(result["results"][0]["price"]["status"], "free")
        self.assertFalse(result["results"][0]["price"]["access_verified"])

    def test_bm25_is_rejected_as_a_search_mode(self):
        status, result = self.request("/search", {"q": "кофейню", "mode": "bm25"})
        self.assertEqual(status, 400)
        self.assertIn("Unsupported search mode", result["error"])
        with self.assertRaises(ValueError):
            make_server(self.engine, 0, default_mode="bm25")

    def test_default_server_never_falls_back_to_bm25(self):
        with make_server(self.engine, 0) as server:
            self.assertEqual(server.default_mode, "relevance")

    def post(self, path, body, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(
                "POST",
                path,
                json.dumps(body),
                {"Content-Type": "application/json", **(headers or {})},
            )
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_profile_endpoint_validates_generation_and_origin(self):
        payload = {"generation": self.engine.generation, "categories": ["business"], "viewed": []}
        status, result = self.post("/recommend", payload)
        self.assertEqual(status, 200)
        self.assertEqual(result["results"][0]["entity_key"], "article:1")
        self.assertEqual(result["results"][0]["price"]["status"], "free")
        self.assertEqual(self.post("/recommend", {**payload, "generation": "stale"})[0], 400)
        self.assertEqual(self.post("/recommend", {**payload, "viewed": ["bad"]})[0], 400)
        self.assertEqual(self.post("/recommend", payload, {"Origin": "https://evil.test"})[0], 403)

    def test_development_plan_validates_profile_and_separates_views(self):
        payload = {"generation": self.engine.generation, "categories": [], "viewed": [], "completed": []}
        status, result = self.post("/development-plan", payload)
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "needs_activity")
        self.assertEqual(self.post("/development-plan", {**payload, "completed": ["article:1"]})[0], 400)
        self.assertEqual(self.post("/development-plan", {**payload, "generation": "old"})[0], 400)
        self.assertEqual(self.post("/development-plan", payload, {"Origin": "https://evil.test"})[0], 403)

    def test_latency_summary_contains_no_query(self):
        self.request("/search", {"q": "кофейня", "mode": "hybrid"})
        self.request("/search", {"q": "кофейня", "mode": "invalid"})
        _, health = self.request("/health")
        self.assertGreaterEqual(health["latency_ms"]["/search"]["n"], 1)
        self.assertGreaterEqual(health["http_errors"]["/search"]["4xx"], 1)
        self.assertNotIn("кофейня", json.dumps(health, ensure_ascii=False))

    def test_health_exposes_explicitly_compatible_profile_generation(self):
        with patch.dict(self.engine.manifest, {"profile_compatible_generations": ["old-generation"]}):
            status, health = self.request("/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["profile_compatible_generations"], ["old-generation"])

    def test_ui_assets_are_allowlisted_and_have_security_headers(self):
        for path, mime in [
            ("/", "text/html"),
            ("/app.js", "text/javascript"),
            ("/app.css", "text/css"),
            ("/favicon.svg", "image/svg+xml"),
        ]:
            with self.subTest(path=path):
                connection = http.client.HTTPConnection(
                    "127.0.0.1", self.server.server_port, timeout=5
                )
                try:
                    connection.request("GET", path)
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertIn(mime, response.getheader("Content-Type"))
                    self.assertIn(
                        "script-src 'self'", response.getheader("Content-Security-Policy")
                    )
                    self.assertTrue(response.read())
                finally:
                    connection.close()
        for path in [
            "/../source.sqlite",
            "/web/../../cli.py",
            "/%2e%2e/source.sqlite",
            "/manifest.json",
        ]:
            self.assertEqual(self.request(path)[0], 404)
        status, health = self.request("/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["catalog_count"], 1)

    def test_busy_port_is_reported_before_model_loading(self):
        args = SimpleNamespace(
            port=self.server.server_port, output=self.temp.name, hybrid=True, open_browser=False
        )
        with patch("alfa_reco.search.SearchEngine") as model:
            with self.assertRaisesRegex(ValueError, "уже занят"):
                serve(args)
            model.assert_not_called()

    def test_failed_initialization_releases_reserved_port(self):
        with make_server(None, 0) as temporary:
            port = temporary.server_port
        args = SimpleNamespace(port=port, output=self.temp.name, hybrid=True, open_browser=False)
        with patch("alfa_reco.search.SearchEngine", side_effect=ValueError("bad catalog")):
            with self.assertRaisesRegex(ValueError, "bad catalog"):
                serve(args)
        with make_server(None, port):
            pass

    def test_end_to_end_selection_and_original_query(self):
        status, suggestions = self.request("/suggest", {"q": "открыть коф"})
        self.assertEqual(status, 200)
        selected = suggestions["completions"][0]
        status, result = self.request(
            "/search",
            {
                "q": "открыть коф",
                "mode": "hybrid",
                "selection_id": selected["id"],
                "selection_generation": suggestions["generation"],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["query"], "открыть коф")
        self.assertTrue(result["results"][0]["selection_match"])

    def test_evidence_and_unverified_constraints_are_returned(self):
        status, result = self.request(
            "/search", {"q": "бесплатная статья о кофейне без опыта", "mode": "hybrid"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            set(result["query_rules"]["unsupported_constraints"]), {"price", "experience"}
        )
        self.assertTrue(result["results"])
        self.assertTrue(result["results"][0]["evidence"]["facts"])
        self.assertEqual(result["confidence"]["status"], "uncertain")

    def test_requested_format_does_not_return_a_different_kind(self):
        status, result = self.request(
            "/search", {"q": "курс по кофейне", "mode": "hybrid"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["results"], [])
        self.assertEqual(result["request_understanding"]["applied_format"], "course")

    def test_clarification_preserves_query_and_selects_a_material(self):
        query = "открыть столовую"
        token = self.engine.clarifications.issue(query, {"kind": "material", "value": "article:1"})
        status, result = self.request(
            "/search", {"q": query, "mode": "hybrid", "clarification_token": token}
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["query"], query)
        self.assertEqual(result["focus"]["label"], "Как открыть кофейню")
        self.assertEqual(result["results"][0]["entity_key"], "article:1")
        self.assertNotEqual(result["confidence"]["status"], "uncertain")
        self.assertEqual(
            self.request(
                "/search", {"q": "новый запрос", "mode": "hybrid", "clarification_token": token}
            )[0],
            400,
        )

    def test_bad_input_stale_selection_and_unknown_routes(self):
        for path, params in [
            ("/suggest", {"q": "x" * 301}),
            ("/suggest", {"limit": "-1"}),
            ("/search", {"q": "коф", "selection_id": "bad", "selection_generation": "old"}),
            ("/search", {"q": "коф", "mode": "invalid"}),
            ("/suggest", {"surprise": "1"}),
        ]:
            self.assertEqual(self.request(path, params)[0], 400)
        self.assertEqual(self.request("/suggest?q=a&q=b")[0], 400)
        self.assertEqual(self.request("/source.sqlite")[0], 404)
        self.assertEqual(self.request("/health", headers={"Host": "external.example"})[0], 403)
        self.assertEqual(self.request("/health")[0], 200)

    def test_parallel_requests_keep_their_query(self):
        from concurrent.futures import ThreadPoolExecutor

        queries = ["коф", "Frontend", "открыть коф", "аренда"] * 3
        with ThreadPoolExecutor(max_workers=4) as executor:
            outputs = list(executor.map(lambda q: self.request("/suggest", {"q": q}), queries))
        self.assertEqual([result["query"] for _, result in outputs], queries)
        self.assertTrue(all(status == 200 for status, _ in outputs))
