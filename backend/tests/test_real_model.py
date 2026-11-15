"""Opt-in end-to-end test using real E5/CatBoost and a disposable trusted test catalog."""

import base64
import json
import os
import tempfile
import unittest
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app import create_app
from config.settings import Settings
from infrastructure.uow import SqlAlchemyUnitOfWork
from schemas.requests import CatalogImport


@unittest.skipUnless(
    os.getenv("ALFA_REAL_RECO_URL") and os.getenv("ALFA_REAL_BUNDLE"),
    "Set ALFA_REAL_RECO_URL and ALFA_REAL_BUNDLE for real-model integration",
)
class RealModelTests(unittest.TestCase):
    def test_public_api_with_real_handoff(self):
        url = os.environ["ALFA_REAL_RECO_URL"]
        bundle = Path(os.environ["ALFA_REAL_BUNDLE"])
        with httpx.Client(base_url=url, timeout=120, trust_env=False) as model:
            state = model.get("/health").raise_for_status().json()
            self.assertEqual(state["default_search_mode"], "relevance")
            self.assertTrue(state["relevance_available"])
            generation = state["generation"]
            query = "Хочу открыть кофейню"
            raw = (
                model.get("/search", params={"q": query, "mode": "relevance", "top": 50})
                .raise_for_status()
                .json()
            )
            self.assertTrue(raw["results"], "Real-model smoke must produce at least one candidate")
            source = json.loads((bundle / "catalog" / generation / "catalog.json").read_text())
            if isinstance(source, dict):
                source = source["materials"]
            catalog = {item["entity_key"]: item for item in source}
            keys = {item["entity_key"] for item in raw["results"] + raw["alternatives"]}
            course = next(key for key, item in catalog.items() if item["kind"] == "course")
            keys.add(course)
            clarification_query = "хочу начать"
            ambiguous = (
                model.get(
                    "/search", params={"q": clarification_query, "mode": "relevance", "top": 5}
                )
                .raise_for_status()
                .json()
            )
            for option in (ambiguous.get("clarification") or {}).get("options", []):
                data = json.loads(base64.urlsafe_b64decode(option["token"])[32:])
                if data["kind"] == "material":
                    keys.add(data["value"])

            forbidden = raw["results"][0]["entity_key"]
            # Publication/access here are explicit TEST fixtures, never inferred production rights.
            materials = [
                {
                    "entity_key": key,
                    "kind": catalog[key]["kind"],
                    "title": "Trusted test title " + str(index),
                    "topics": catalog[key].get("topics", []),
                    "published": True,
                    "access": "restricted" if key == forbidden else "public",
                }
                for index, key in enumerate(sorted(keys))
            ]
            with tempfile.TemporaryDirectory() as directory:
                app = create_app(
                    Settings(
                        database_url="sqlite:///" + str(Path(directory) / "test.sqlite3"),
                        reco_mode="http",
                        reco_url=url,
                        request_timeout=120,
                    )
                )
                with TestClient(app) as api:
                    with SqlAlchemyUnitOfWork(app.state.sessions) as uow:
                        uow.repository.import_catalog(
                            CatalogImport.model_validate(
                                {"generation": generation, "materials": materials}
                            )
                        )
                        uow.commit()
                    token = api.post(
                        "/api/v1/auth/register",
                        json={"username": "realmodel", "password": "integration-password-123"},
                    )
                    self.assertEqual(token.status_code, 201, token.text)
                    headers = {"Authorization": "Bearer " + token.json()["access_token"]}
                    ready = api.get("/ready")
                    self.assertEqual(ready.status_code, 200, ready.text)
                    response = api.get("/api/v1/search", params={"q": query}, headers=headers)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertNotIn(
                        forbidden,
                        {
                            item["entity_key"]
                            for item in response.json()["results"] + response.json()["alternatives"]
                        },
                    )
                    for item in response.json()["results"]:
                        self.assertTrue(item["title"].startswith("Trusted test title"))
                    self.assertIn("confidence", response.json())
                    self.assertEqual(
                        api.get(
                            "/api/v1/suggest", params={"q": "бизнес"}, headers=headers
                        ).status_code,
                        200,
                    )
                    suggestion_query = catalog[course]["title"][:100]
                    suggestions = (
                        api.get(
                            "/api/v1/suggest",
                            params={"q": suggestion_query, "limit": 10},
                            headers=headers,
                        )
                        .raise_for_status()
                        .json()
                    )
                    choice = next(
                        item
                        for item in suggestions["completions"]
                        if item["kind"] == "title" and item["entity_key"] == course
                    )
                    selected = api.get(
                        "/api/v1/search",
                        params={
                            "q": suggestion_query,
                            "selection_id": choice["id"],
                            "selection_generation": generation,
                        },
                        headers=headers,
                    )
                    self.assertEqual(selected.status_code, 200, selected.text)
                    clarified = (
                        api.get(
                            "/api/v1/search", params={"q": clarification_query}, headers=headers
                        )
                        .raise_for_status()
                        .json()
                    )
                    self.assertTrue(clarified["clarification"]["options"])
                    token = clarified["clarification"]["options"][0]["token"]
                    followup = api.get(
                        "/api/v1/search",
                        params={"q": clarification_query, "clarification_token": token},
                        headers=headers,
                    )
                    self.assertEqual(followup.status_code, 200, followup.text)
                    api.put(
                        "/api/v1/me/profile", json={"categories": ["business"]}, headers=headers
                    ).raise_for_status()
                    event = api.post(
                        "/api/v1/me/events",
                        json={
                            "generation": generation,
                            "event_id": "real-view",
                            "entity_key": course,
                            "action": "viewed",
                        },
                        headers=headers,
                    )
                    self.assertEqual(event.status_code, 201, event.text)
                    for endpoint in ("recommend", "development-plan"):
                        response = api.post(
                            "/api/v1/" + endpoint, json={"generation": generation}, headers=headers
                        )
                        self.assertEqual(response.status_code, 200, response.text)
                        self.assertEqual(response.json()["generation"], generation)
