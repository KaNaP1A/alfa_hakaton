from __future__ import annotations

import re

import httpx
from pydantic import TypeAdapter, ValidationError

from config.settings import Settings
from domain.entities import Material
from domain.errors import UpstreamError as UpstreamError
from domain.types import JsonObject


class HttpRecommender:
    def __init__(self, settings: Settings) -> None:
        self.client = httpx.Client(
            base_url=settings.reco_url.rstrip("/"),
            timeout=settings.request_timeout,
            trust_env=False,
            headers={"Host": settings.reco_host_header} if settings.reco_host_header else None,
        )

    def close(self) -> None:
        self.client.close()

    def _request(
        self, path: str, params: dict[str, str | int] | None = None, body: JsonObject | None = None
    ) -> JsonObject:
        try:
            response = self.client.request(
                "POST" if body is not None else "GET", path, params=params, json=body
            )
            if response.status_code == 400:
                raise UpstreamError(400, "Algorithm rejected the request; refresh and try again")
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Invalid response")
            return TypeAdapter(JsonObject).validate_python(payload)
        except httpx.TimeoutException as error:
            raise UpstreamError(504, "Recommendation service timed out") from error
        except (httpx.HTTPError, ValueError, ValidationError) as error:
            raise UpstreamError(
                502, "Recommendation service unavailable or invalid response"
            ) from error

    def health(self) -> JsonObject:
        return self._request("/health")

    def search(
        self,
        q: str,
        top: int,
        kind: str | None = None,
        clarification_text: str | None = None,
        selection_id: str | None = None,
        selection_generation: str | None = None,
        clarification_token: str | None = None,
    ) -> JsonObject:
        params: dict[str, str | int] = {"q": q, "mode": "relevance", "top": top}
        if kind:
            params["kind"] = kind
        if clarification_text:
            params["clarification_text"] = clarification_text
        for key, value in {
            "selection_id": selection_id,
            "selection_generation": selection_generation,
            "clarification_token": clarification_token,
        }.items():
            if value is not None:
                params[key] = value
        return self._request("/search", params=params)

    def suggest(self, q: str, limit: int) -> JsonObject:
        return self._request("/suggest", params={"q": q, "limit": limit})

    def interests(self) -> JsonObject:
        return self._request("/interests")

    def recommend_by_interests(
        self, generation: str, categories: list[str], facets: list[str], viewed: list[str]
    ) -> JsonObject:
        return self._request(
            "/recommend-by-interests",
            body=TypeAdapter(JsonObject).validate_python(
                {
                    "generation": generation,
                    "categories": categories,
                    "selected_facets": facets,
                    "viewed": viewed,
                }
            ),
        )

    def recommend(
        self,
        generation: str,
        categories: list[str],
        viewed: list[str],
        completed: list[str] | None = None,
    ) -> JsonObject:
        body: JsonObject = {
            "generation": generation,
            "categories": [c for c in categories],
            "viewed": [v for v in viewed],
        }
        if completed is not None:
            body["completed"] = [c for c in completed]
        return self._request(
            "/development-plan" if completed is not None else "/recommend", body=body
        )


class DemoRecommender:
    """Transparent lexical demo. Never pretends to load E5/CatBoost."""

    def __init__(self, materials: list[Material], generation: str) -> None:
        self.materials = materials
        self.generation = generation

    def close(self) -> None:
        pass

    def health(self) -> JsonObject:
        return TypeAdapter(JsonObject).validate_python(
            {"status": "ok", "generation": self.generation}
        )

    def search(
        self,
        q: str,
        top: int,
        kind: str | None = None,
        clarification_text: str | None = None,
        selection_id: str | None = None,
        selection_generation: str | None = None,
        clarification_token: str | None = None,
    ) -> JsonObject:
        terms = set(re.findall("\\w+", (q + " " + (clarification_text or "")).casefold()))
        ranked = []
        for item in self.materials:
            if kind and item.kind != kind:
                continue
            text = f"{item.title} {item.description} {' '.join(item.topics)}".casefold()
            score = sum((term in text for term in terms))
            if score:
                ranked.append((score, item.entity_key))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]))
        return TypeAdapter(JsonObject).validate_python(
            {
                "generation": self.generation,
                "results": [{"entity_key": key} for _, key in ranked[:top]],
                "alternatives": [],
                "clarification": None,
            }
        )

    def suggest(self, q: str, limit: int) -> JsonObject:
        return {"generation": self.generation, "completions": [], "related_topics": []}

    def interests(self) -> JsonObject:
        facets = {
            "business": ("Бизнес", {"Бизнес", "Развитие бизнеса", "Старт бизнеса"}),
            "finance": ("Финансы", {"Финансы", "Финансы и учет", "Налоги и законы"}),
            "team": ("Команда", {"Команда", "Управление командой", "Поиск сотрудников"}),
            "marketing": ("Маркетинг", {"Маркетинг", "Продажи", "Продвижение продукта"}),
            "technology": ("Технологии", {"Технологии", "Анализ данных", "Работа с данными"}),
        }
        categories = []
        for identifier, (label, names) in facets.items():
            topics = []
            relevant: set[str] = set()
            for name in sorted(names):
                keys = {m.entity_key for m in self.materials if name in m.topics}
                if keys:
                    relevant.update(keys)
                    topics.append(
                        {
                            "value": name,
                            "label": name,
                            "sources": ["topics"],
                            "material_count": len(keys),
                        }
                    )
            if topics:
                categories.append(
                    {
                        "id": identifier,
                        "label": label,
                        "material_count": len(relevant),
                        "topics": topics,
                    }
                )
        return TypeAdapter(JsonObject).validate_python(
            {"generation": self.generation, "categories": categories}
        )

    def recommend_by_interests(
        self, generation: str, categories: list[str], facets: list[str], viewed: list[str]
    ) -> JsonObject:
        if generation != self.generation:
            raise UpstreamError(400, "Catalog changed; refresh and try again")
        directory = self.interests()
        allowed: set[str] = set()
        groups = directory.get("categories")
        if isinstance(groups, list):
            for group in groups:
                if not isinstance(group, dict) or group.get("id") not in categories:
                    continue
                topics = group.get("topics")
                if isinstance(topics, list):
                    for topic in topics:
                        if isinstance(topic, dict):
                            value = topic.get("value")
                            if isinstance(value, str):
                                allowed.add(value)
        if any(facet not in allowed for facet in facets):
            raise UpstreamError(400, "Selected topic is not available")
        chosen = set(facets) if facets else allowed
        items = [
            {"entity_key": m.entity_key}
            for m in self.materials
            if m.entity_key not in viewed and chosen.intersection(m.topics)
        ]
        return TypeAdapter(JsonObject).validate_python(
            {
                "generation": generation,
                "results": items[:5],
                "status": "ok" if len(items) >= 5 else "insufficient_evidence",
            }
        )

    def recommend(
        self,
        generation: str,
        categories: list[str],
        viewed: list[str],
        completed: list[str] | None = None,
    ) -> JsonObject:
        facets = {
            "business": "Бизнес",
            "finance": "Финансы",
            "team": "Команда",
            "marketing": "Маркетинг",
            "technology": "Технологии",
        }
        interests = {facets[c] for c in categories}
        interests.update((t for m in self.materials if m.entity_key in viewed for t in m.topics))
        items = [
            {"entity_key": m.entity_key}
            for m in self.materials
            if m.entity_key not in viewed and interests.intersection(m.topics)
        ]
        if completed is None:
            return TypeAdapter(JsonObject).validate_python(
                {"generation": generation, "results": items[:5]}
            )
        return TypeAdapter(JsonObject).validate_python(
            {
                "generation": generation,
                "status": "partial" if items and viewed else "needs_activity",
                "steps": [{"number": i + 1, "material": item} for i, item in enumerate(items[:3])]
                if viewed
                else [],
            }
        )
