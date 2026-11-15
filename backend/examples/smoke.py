"""End-to-end check of a running seeded demo; use a unique throwaway account."""

import secrets
import sys

import httpx

base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
with httpx.Client(base_url=base_url, timeout=35) as client:
    health = client.get("/health")
    health.raise_for_status()
    if not health.json().get("demo"):
        raise SystemExit("This script is for the fictional demo catalog only")
    generation = health.json()["generation"]
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "review-" + secrets.token_hex(6),
            "password": secrets.token_urlsafe(24),
        },
    )
    response.raise_for_status()
    client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
    response = client.put("/api/v1/me/profile", json={"categories": ["business"]})
    response.raise_for_status()
    for route in ["/ready", "/api/v1/catalog", "/api/v1/suggest?q=кофей", "/api/v1/search?q=кофей"]:
        response = client.get(route)
        response.raise_for_status()
        assert "course:demo-private" not in response.text, route
        print(route, response.status_code)
    event = {
        "generation": generation,
        "event_id": "smoke-completion",
        "entity_key": "course:demo-coffee",
        "action": "completed",
    }
    response = client.post("/api/v1/me/events", json=event)
    response.raise_for_status()
    response = client.post("/api/v1/me/events", json=event)
    response.raise_for_status()
    assert response.json()["duplicate"]
    for route in ["/api/v1/recommend", "/api/v1/development-plan"]:
        response = client.post(route, json={"generation": generation})
        response.raise_for_status()
        assert "course:demo-private" not in response.text
        print(route, response.status_code)
    response = client.post("/api/v1/auth/logout")
    response.raise_for_status()
    assert client.get("/api/v1/me").status_code == 401
print("Demo smoke passed: auth, catalog, access, search, history, recommendations, plan, logout")
