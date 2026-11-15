import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import create_app
from cli import DEMO
from config.settings import Settings
from infrastructure.auth import password_hash, password_matches, token_digest
from infrastructure.database import Activity, Grant, Material, SessionToken, User
from infrastructure.recommender import HttpRecommender, UpstreamError
from repositories.catalog import import_catalog
from schemas.requests import CatalogImport


class FakeRecommender:
    def __init__(self):
        self.generation = "demo-v1"
        self.last_history = None
        self.results = [
            {"entity_key": "course:demo-private", "title": "LEAK", "reason": "LEAK"},
            {
                "entity_key": "course:demo-coffee",
                "title": "FORGED",
                "canonical_url": "javascript:x",
                "price": {"amount": "999"},
                "evidence": {"text": "LEAK"},
            },
            {"entity_key": "course:demo-coffee"},
            {"entity_key": "unknown:id", "title": "LEAK"},
        ]
        self.steps = [{"material": {"entity_key": "course:demo-coffee"}, "why": "LEAK"}]
        self.error = None

    def close(self):
        pass

    def health(self):
        return {"status": "ok", "generation": self.generation, "relevance_available": True}

    def suggest(self, q, limit):
        return {"generation": self.generation, "completions": [], "related_topics": []}

    def search(self, *args, **kwargs):
        if self.error:
            raise self.error
        return {
            "generation": self.generation,
            "results": self.results,
            "alternatives": [{"entity_key": "course:demo-private"}],
            "clarification": {"question": "LEAK", "options": ["LEAK"]},
        }

    def recommend(self, generation, categories, viewed, completed=None):
        self.last_history = (categories, viewed, completed)
        return {
            "generation": self.generation,
            "results": self.results,
            "steps": self.steps,
            "status": "ready",
        }


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(
            database_url=os.environ.get(
                "ALFA_TEST_DATABASE_URL", "sqlite:///" + str(Path(self.temp.name) / "test.sqlite3")
            ),
            requests_per_minute=10000,
        )
        if "ALFA_TEST_DATABASE_URL" in os.environ:
            from sqlalchemy.engine import make_url

            if not make_url(self.settings.database_url).database.endswith("_test"):
                raise RuntimeError("Use a dedicated database whose name ends with _test")
        self.upstream = FakeRecommender()
        self.app = create_app(self.settings, recommender=self.upstream)
        self.client = TestClient(self.app)
        self.client.__enter__()
        with self.app.state.sessions() as db:
            from infrastructure.database import Base

            Base.metadata.drop_all(self.app.state.engine)
            Base.metadata.create_all(self.app.state.engine)
            import_catalog(db, CatalogImport.model_validate(DEMO))
            db.commit()
        self.auth = self.register("alice")
        self.other_auth = self.register("bob")

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def register(self, name):
        response = self.client.post(
            "/api/v1/auth/register", json={"username": name, "password": "a-long-password-123"}
        )
        self.assertEqual(response.status_code, 201, response.text)
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    def get(self, path, auth=None):
        return self.client.get(path, headers=auth or self.auth)

    def post(self, path, data, auth=None):
        return self.client.post(path, json=data, headers=auth or self.auth)

    def event(
        self,
        key="course:demo-coffee",
        action="viewed",
        eid="event-1",
        auth=None,
        generation="demo-v1",
    ):
        return self.post(
            "/api/v1/me/events",
            {"event_id": eid, "entity_key": key, "action": action, "generation": generation},
            auth,
        )

    def test_error_envelope_is_shared_by_failure_paths(self):
        responses = [
            self.client.get("/api/v1/me"),
            self.client.get("/missing"),
            self.client.delete("/api/v1/me"),
            self.post("/api/v1/auth/login", {"username": "xy", "password": "secret"}),
            self.client.post("/api/v1/auth/login", content=b"x" * 32769),
            self.event(key="course:missing"),
            self.post("/api/v1/recommend", {"generation": "old"}),
        ]
        for response in responses:
            with self.subTest(status=response.status_code):
                self.assertGreaterEqual(response.status_code, 400)
                self.assertEqual(set(response.json()), {"error"})
                self.assertEqual(set(response.json()["error"]), {"code", "message", "details"})
                self.assertNotIn("secret", response.text)
                self.assertIn("X-Request-ID", response.headers)

    def test_openapi_documents_error_contract(self):
        schema = self.client.get("/openapi.json").json()
        response = schema["paths"]["/api/v1/auth/login"]["post"]["responses"]["422"]
        self.assertEqual(
            response["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/ErrorEnvelope",
        )

    def test_requires_authentication(self):
        for path in ["/api/v1/catalog", "/api/v1/me", "/api/v1/search?q=кофейня"]:
            self.assertEqual(self.client.get(path).status_code, 401)

    def test_login_logout_and_hashed_tokens(self):
        token = self.auth["Authorization"].split()[1]
        with self.app.state.sessions() as db:
            self.assertIsNotNone(db.get(SessionToken, token_digest(token)))
            self.assertIsNone(db.get(SessionToken, token))
            user = db.scalar(select(User).where(User.username == "alice"))
            self.assertNotEqual(user.password_hash, "a-long-password-123")
        self.assertEqual(
            self.post(
                "/api/v1/auth/login", {"username": "ALICE", "password": "a-long-password-123"}
            ).status_code,
            200,
        )
        self.assertEqual(
            self.post(
                "/api/v1/auth/login", {"username": "alice", "password": "wrong-password"}
            ).status_code,
            401,
        )
        self.assertEqual(self.post("/api/v1/auth/logout", {}).status_code, 204)
        self.assertEqual(self.get("/api/v1/me").status_code, 401)

    def test_password_whitespace_is_preserved(self):
        secret = "  long-password  "
        encoded = password_hash(secret)
        self.assertTrue(password_matches(secret, encoded))
        self.assertFalse(password_matches(secret.strip(), encoded))
        self.assertEqual(
            self.post(
                "/api/v1/auth/register", {"username": "spaces", "password": secret}
            ).status_code,
            201,
        )
        self.assertEqual(
            self.post(
                "/api/v1/auth/login", {"username": "spaces", "password": secret.strip()}
            ).status_code,
            401,
        )

    def test_expired_token_and_duplicate_registration(self):
        self.assertEqual(
            self.post(
                "/api/v1/auth/register", {"username": "alice", "password": "a-long-password-123"}
            ).status_code,
            409,
        )
        with self.app.state.sessions() as db:
            token = db.get(SessionToken, token_digest(self.auth["Authorization"].split()[1]))
            token.expires_at = time.time() - 1
            db.commit()
        self.assertEqual(self.get("/api/v1/me").status_code, 401)

    def test_catalog_and_suggestions_filter_private_and_unpublished(self):
        with self.app.state.sessions() as db:
            db.get(Material, "article:demo-budget").published = False
            db.commit()
        body = self.get("/api/v1/catalog").json()
        self.assertEqual(body["total"], 2)
        self.assertNotIn("Закрытый", json.dumps(body, ensure_ascii=False))
        self.assertEqual(self.get("/api/v1/suggest?q=Закрытый").json()["completions"], [])
        self.assertEqual(self.get("/api/v1/suggest?q=кофей").status_code, 200)

    def test_grants_are_user_specific_and_revocable(self):
        with self.app.state.sessions() as db:
            user = db.scalar(select(User).where(User.username == "alice"))
            grant = Grant(user_id=user.id, entity_key="course:demo-private")
            db.add(grant)
            db.commit()
            self.assertEqual(self.get("/api/v1/catalog").json()["total"], 4)
            self.assertEqual(self.get("/api/v1/catalog", self.other_auth).json()["total"], 3)
            grant.expires_at = time.time() - 1
            db.commit()
        self.assertEqual(self.get("/api/v1/catalog").json()["total"], 3)

    def test_search_enriches_without_leaking_upstream_fields(self):
        response = self.get("/api/v1/search?q=кофейня")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("LEAK", response.text)
        self.assertNotIn("FORGED", response.text)
        self.assertNotIn("javascript:", response.text)
        self.assertEqual(len(response.json()["results"]), 1)
        item = response.json()["results"][0]
        self.assertEqual(item["title"], "Открываем кофейню")
        self.assertEqual(item["price"]["status"], "unknown")
        self.assertEqual(response.json()["alternatives"], [])

    def test_current_price_and_url_override_snapshot(self):
        with self.app.state.sessions() as db:
            material = db.get(Material, "course:demo-coffee")
            material.price_amount = "123.45"
            material.price_currency = "RUB"
            material.canonical_url = "https://example.org/actual-course"
            db.commit()
        item = self.get("/api/v1/search?q=кофе").json()["results"][0]
        self.assertEqual(item["price"]["amount"], "123.45")
        self.assertEqual(item["canonical_url"], "https://example.org/actual-course")

    def test_generation_mismatch_is_explicit(self):
        self.upstream.generation = "new-generation"
        self.assertEqual(self.get("/api/v1/search?q=кофе").status_code, 409)
        self.assertEqual(self.get("/ready").status_code, 409)
        self.assertEqual(self.post("/api/v1/recommend", {"generation": "old"}).status_code, 409)
        self.assertEqual(self.event(generation="old").status_code, 409)

    def test_events_are_idempotent_and_isolated(self):
        self.assertEqual(self.event().status_code, 201)
        self.assertTrue(self.event().json()["duplicate"])
        self.assertEqual(self.event(action="completed").status_code, 409)
        self.assertEqual(len(self.get("/api/v1/me/events").json()["items"]), 1)
        self.assertEqual(self.get("/api/v1/me/events", self.other_auth).json()["items"], [])
        self.assertEqual(self.event(key="course:demo-private", eid="hidden").status_code, 404)
        self.assertEqual(self.event(key="article:demo-budget", action="completed").status_code, 422)
        self.assertEqual(
            self.post(
                "/api/v1/me/events",
                {
                    "generation": "demo-v1",
                    "event_id": "purchase",
                    "entity_key": "course:demo-coffee",
                    "action": "purchased",
                },
            ).status_code,
            422,
        )

    def test_history_and_profile_are_built_on_server(self):
        response = self.client.put(
            "/api/v1/me/profile", headers=self.auth, json={"categories": ["business"]}
        )
        self.assertEqual(response.status_code, 200)
        self.event(action="completed")
        self.event(action="viewed", eid="new-view")
        self.post("/api/v1/development-plan", {"generation": "demo-v1"})
        categories, viewed, completed = self.upstream.last_history
        self.assertEqual(categories, ["business"])
        self.assertEqual(viewed, ["course:demo-coffee"])
        self.assertEqual(completed, ["course:demo-coffee"])
        self.assertEqual(
            self.post(
                "/api/v1/recommend", {"generation": "demo-v1", "viewed": ["forged"]}
            ).status_code,
            422,
        )

    def test_access_rechecked_for_history_and_recommendations(self):
        self.event()
        with self.app.state.sessions() as db:
            db.get(Material, "course:demo-coffee").published = False
            db.commit()
        response = self.post("/api/v1/recommend", {"generation": "demo-v1"})
        self.assertEqual(response.json()["results"], [])
        self.assertEqual(self.upstream.last_history[1], [])
        self.assertEqual(self.get("/api/v1/me/events").json()["items"], [])

    def test_plan_does_not_leak_explanations_or_retain_broken_sequence(self):
        response = self.post("/api/v1/development-plan", {"generation": "demo-v1"})
        self.assertNotIn("LEAK", response.text)
        self.assertEqual(response.json()["steps"][0]["number"], 1)
        self.upstream.steps.append({"material": {"entity_key": "course:demo-private"}})
        response = self.post("/api/v1/development-plan", {"generation": "demo-v1"})
        self.assertEqual(response.json()["steps"], [])
        self.assertEqual(response.json()["status"], "insufficient_evidence")

    def test_catalog_replacement_ignores_old_history(self):
        self.event()
        data = dict(DEMO, generation="demo-v2")
        with self.app.state.sessions() as db:
            import_catalog(db, CatalogImport.model_validate(data))
            db.commit()
            self.assertEqual(len(list(db.scalars(select(Activity)))), 1)
        self.upstream.generation = "demo-v2"
        response = self.post("/api/v1/recommend", {"generation": "demo-v2"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.upstream.last_history[1], [])

    def test_timeout_and_malformed_upstream(self):
        self.upstream.error = UpstreamError(504, "Recommendation service timed out")
        self.assertEqual(self.get("/api/v1/search?q=кофе").status_code, 504)
        self.upstream.error = None
        self.upstream.results = ["malformed"]
        self.assertEqual(self.get("/api/v1/search?q=кофе").status_code, 502)

    def test_empty_results_and_invalid_input(self):
        self.upstream.results = []
        self.assertEqual(self.get("/api/v1/search?q=кофе").json()["results"], [])
        for query in ["", " " * 3, "x" * 301, "\x01"]:
            response = self.client.get("/api/v1/search", params={"q": query}, headers=self.auth)
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.get("/api/v1/search?q=x&top=51").status_code, 422)
        self.assertEqual(self.get("/api/v1/catalog?kind=lesson").status_code, 422)

    def test_public_health_headers_and_documentation(self):
        response = self.client.get("/health")
        self.assertTrue(response.json()["demo"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("X-Request-ID", response.headers)
        self.assertEqual(self.client.get("/docs").status_code, 200)
        self.assertEqual(self.client.get("/openapi.json").status_code, 200)
        self.assertEqual(self.client.get("/ready").status_code, 200)

    def test_validation_does_not_echo_passwords(self):
        response = self.post("/api/v1/auth/register", {"username": "xy", "password": "secret"})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("secret", response.text)

    def test_body_limit(self):
        response = self.client.post("/api/v1/auth/login", content=b"x" * 32769)
        self.assertEqual(response.status_code, 413)

    def test_demo_works_without_models_and_survives_restart(self):
        self.client.__exit__(None, None, None)
        demo_app = create_app(self.settings)
        self.app = demo_app
        self.client = TestClient(demo_app)
        self.client.__enter__()
        self.assertEqual(self.get("/api/v1/me").json()["username"], "alice")
        result = self.get("/api/v1/search?q=кофейни")
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()["results"])
        self.assertEqual(result.json()["mode"], "demo")

    def test_catalog_validation_fails_before_replacement(self):
        invalid = dict(
            DEMO, materials=[dict(DEMO["materials"][0], canonical_url="javascript:alert(1)")]
        )
        with self.assertRaises(ValueError):
            CatalogImport.model_validate(invalid)
        with self.assertRaises(ValueError):
            CatalogImport.model_validate(dict(DEMO, materials=DEMO["materials"] * 2))
        self.assertEqual(self.get("/api/v1/catalog").json()["total"], 3)

    def test_model_suggestions_are_authorized_and_selectable(self):
        payload = {
            "generation": "demo-v1",
            "completions": [
                {
                    "id": "safe-id",
                    "kind": "title",
                    "label": "FORGED",
                    "evidence_entity_keys": ["course:demo-coffee"],
                    "support_count": 1,
                },
                {
                    "id": "secret-id",
                    "kind": "title",
                    "label": "LEAK",
                    "evidence_entity_keys": ["course:demo-private"],
                    "support_count": 1,
                },
                {
                    "id": "partial-id",
                    "kind": "title",
                    "label": "LEAK",
                    "evidence_entity_keys": ["course:demo-coffee"],
                    "support_count": 99,
                },
            ],
            "related_topics": [],
        }
        with patch.object(self.upstream, "suggest", return_value=payload):
            response = self.get("/api/v1/suggest?q=кофе")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual([item["id"] for item in response.json()["completions"]], ["safe-id"])
            self.assertNotIn("FORGED", response.text)
            self.assertNotIn("LEAK", response.text)
            response = self.get(
                "/api/v1/search?q=кофе&selection_id=safe-id&selection_generation=demo-v1"
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(
                self.get(
                    "/api/v1/search?q=кофе&selection_id=secret-id&selection_generation=demo-v1"
                ).status_code,
                404,
            )
            self.assertEqual(
                self.get(
                    "/api/v1/search?q=кофе&selection_id=safe-id&selection_generation=old"
                ).status_code,
                409,
            )

    def test_search_rejects_incompatible_choices(self):
        for params in (
            {"selection_id": "x"},
            {"clarification_token": "x", "clarification_text": "y"},
            {"selection_id": "x", "selection_generation": "demo-v1", "clarification_text": "y"},
        ):
            response = self.client.get(
                "/api/v1/search", params={"q": "кофе", **params}, headers=self.auth
            )
            self.assertEqual(response.status_code, 422, response.text)

    def test_confidence_is_not_forwarded_as_arbitrary_model_data(self):
        original = self.upstream.search("кофе")
        original["confidence"] = {"status": "unvalidated", "reason": "LEAK", "secret": "LEAK"}
        with patch.object(self.upstream, "search", return_value=original):
            response = self.get("/api/v1/search?q=кофе")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["confidence"], {"status": "unvalidated"})
            self.assertNotIn("LEAK", response.text)


class AdapterTests(unittest.TestCase):
    def test_http_contract_and_errors(self):
        service = HttpRecommender(Settings(reco_mode="http"))
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"generation": "g", "results": []})

        service.client.close()
        service.client = httpx.Client(
            base_url="http://127.0.0.1:8000", transport=httpx.MockTransport(handler)
        )
        service.search("кофе", 5, "course", "бюджет")
        self.assertEqual(requests[0].url.params["mode"], "relevance")
        self.assertEqual(requests[0].url.params["clarification_text"], "бюджет")
        service.recommend("g", ["business"], ["article:1"], ["course:1"])
        self.assertEqual(requests[1].url.path, "/development-plan")
        self.assertEqual(json.loads(requests[1].content)["completed"], ["course:1"])
        with patch.object(service.client, "request", side_effect=httpx.ReadTimeout("secret")):
            with self.assertRaises(UpstreamError) as raised:
                service.health()
            self.assertEqual(raised.exception.status, 504)
            self.assertNotIn("secret", raised.exception.message)
        service.close()

    def test_cors_allows_only_configured_frontend(self):
        with TestClient(
            create_app(
                Settings(database_url="sqlite:///:memory:", cors_origins=("http://localhost:5173",))
            )
        ) as client:
            allowed = client.options(
                "/api/v1/me",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "Authorization",
                },
            )
            self.assertEqual(allowed.status_code, 200)
            self.assertEqual(
                allowed.headers["access-control-allow-origin"], "http://localhost:5173"
            )
            forbidden = client.options(
                "/api/v1/me",
                headers={
                    "Origin": "https://untrusted.example",
                    "Access-Control-Request-Method": "GET",
                },
            )
            self.assertNotIn("access-control-allow-origin", forbidden.headers)

    def test_rate_limit(self):
        with TestClient(
            create_app(Settings(database_url="sqlite:///:memory:", requests_per_minute=1))
        ) as client:
            self.assertEqual(client.get("/openapi.json").status_code, 200)
            self.assertEqual(client.get("/openapi.json").status_code, 429)


if __name__ == "__main__":
    unittest.main()
