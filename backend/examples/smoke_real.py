"""Exercise a running HTTP-mode backend using a disposable user and real model results."""

import json
import secrets
import sys
import time

import httpx


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
    report = []
    with httpx.Client(base_url=url, timeout=120, trust_env=False) as client:
        health = client.get("/health").raise_for_status().json()
        assert health["mode"] == "http", "Real-model smoke requires ALFA_RECO_MODE=http"
        generation = health["generation"]
        client.get("/ready").raise_for_status()
        assert client.get("/api/v1/me").status_code == 401
        token = (
            client.post(
                "/api/v1/auth/register",
                json={
                    "username": "model-smoke-" + secrets.token_hex(6),
                    "password": secrets.token_urlsafe(24),
                },
            )
            .raise_for_status()
            .json()["access_token"]
        )
        client.headers["Authorization"] = "Bearer " + token
        try:
            client.put("/api/v1/me/profile", json={"categories": ["finance"]}).raise_for_status()
            catalog = client.get("/api/v1/catalog").raise_for_status().json()
            assert catalog["total"] > 0
            report.append({"scenario": "catalog", "materials": catalog["total"]})
            cold = (
                client.post("/api/v1/recommend", json={"generation": generation})
                .raise_for_status()
                .json()
            )
            assert cold["results"], "Cold-start recommendations unexpectedly empty"
            report.append({"scenario": "cold_start", "results": len(cold["results"])})
            empty = (
                client.post("/api/v1/development-plan", json={"generation": generation})
                .raise_for_status()
                .json()
            )
            assert empty["status"] == "needs_activity" and empty["steps"] == []
            report.append({"scenario": "plan_without_history", "status": empty["status"]})
            activity = None
            for query in [
                "Хочу открыть кофейню",
                "найм сотрудников",
                "налоги для ИП",
                "квантовая телепортация",
            ]:
                start = time.perf_counter()
                response = (
                    client.get("/api/v1/search", params={"q": query}).raise_for_status().json()
                )
                assert response["generation"] == generation and response["mode"] == "http"
                assert bool(response["results"]) == (query != "квантовая телепортация")
                assert len({item["entity_key"] for item in response["results"]}) == len(
                    response["results"]
                )
                report.append(
                    {
                        "scenario": "search",
                        "query": query,
                        "results": len(response["results"]),
                        "elapsed_ms": round((time.perf_counter() - start) * 1000, 1),
                    }
                )
                if query == "налоги для ИП":
                    activity = response["results"][0]
            assert activity is not None
            suggestions = (
                client.get("/api/v1/suggest", params={"q": activity["title"], "limit": 10})
                .raise_for_status()
                .json()
            )
            choice = next(item for item in suggestions["completions"] if item["kind"] == "title")
            selected = (
                client.get(
                    "/api/v1/search",
                    params={
                        "q": activity["title"],
                        "selection_id": choice["id"],
                        "selection_generation": choice["selection_generation"],
                    },
                )
                .raise_for_status()
                .json()
            )
            assert choice["entity_key"] in {item["entity_key"] for item in selected["results"]}
            report.append({"scenario": "suggestion_selection", "status": "ok"})
            ambiguous = (
                client.get("/api/v1/search", params={"q": "хочу начать"}).raise_for_status().json()
            )
            option = ambiguous["clarification"]["options"][0]
            client.get(
                "/api/v1/search",
                params={"q": "хочу начать", "clarification_token": option["token"]},
            ).raise_for_status()
            report.append({"scenario": "clarification", "status": "ok"})
            event = {
                "generation": generation,
                "event_id": "view-tax",
                "entity_key": activity["entity_key"],
                "action": "viewed",
            }
            first = client.post("/api/v1/me/events", json=event).raise_for_status().json()
            second = client.post("/api/v1/me/events", json=event).raise_for_status().json()
            assert not first["duplicate"] and second["duplicate"]
            assert len(client.get("/api/v1/me/events").raise_for_status().json()["items"]) == 1
            report.append({"scenario": "history_idempotency", "status": "ok"})
            for endpoint, field in [("recommend", "results"), ("development-plan", "steps")]:
                response = (
                    client.post("/api/v1/" + endpoint, json={"generation": generation})
                    .raise_for_status()
                    .json()
                )
                assert response[field], f"{endpoint} silently lost real-model results"
                report.append(
                    {
                        "scenario": endpoint,
                        "results": len(response[field]),
                        "status": response.get("status", "ok"),
                    }
                )
            assert (
                client.post("/api/v1/recommend", json={"generation": "outdated"}).status_code == 409
            )
            report.append({"scenario": "stale_generation", "status": 409})
        finally:
            client.post("/api/v1/auth/logout").raise_for_status()
        assert client.get("/api/v1/me").status_code == 401
        report.append({"scenario": "logout", "status": "ok"})
    print(
        json.dumps(
            {"status": "passed", "generation": generation, "checks": report},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
