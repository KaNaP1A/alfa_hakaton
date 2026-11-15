import re

import httpx


class UpstreamError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message
        super().__init__(message)


class HttpRecommender:
    def __init__(self, settings):
        self.client = httpx.Client(
            base_url=settings.reco_url.rstrip("/"),
            timeout=settings.request_timeout,
            headers={"Host": settings.reco_host_header} if settings.reco_host_header else None,
        )

    def close(self):
        self.client.close()

    def _request(self, path, params=None, body=None):
        try:
            response = self.client.request(
                "POST" if body is not None else "GET",
                path,
                params=params,
                json=body,
            )
            if response.status_code == 400:
                raise UpstreamError(400, "Algorithm rejected the request; refresh and try again")
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Invalid response")
            return payload
        except httpx.TimeoutException as error:
            raise UpstreamError(504, "Recommendation service timed out") from error
        except (httpx.HTTPError, ValueError) as error:
            raise UpstreamError(
                502, "Recommendation service unavailable or invalid response"
            ) from error

    def health(self):
        return self._request("/health")

    def search(self, q, top, kind=None, clarification_text=None):
        params = {"q": q, "mode": "relevance", "top": top}
        if kind:
            params["kind"] = kind
        if clarification_text:
            params["clarification_text"] = clarification_text
        return self._request("/search", params=params)

    def recommend(self, generation, categories, viewed, completed=None):
        body = {"generation": generation, "categories": categories, "viewed": viewed}
        if completed is not None:
            body["completed"] = completed
        return self._request(
            "/development-plan" if completed is not None else "/recommend",
            body=body,
        )


class DemoRecommender:
    """Transparent lexical demo. Never pretends to load E5/CatBoost."""

    def __init__(self, materials, generation):
        self.materials = materials
        self.generation = generation

    def close(self):
        pass

    def health(self):
        return {"status": "ok", "generation": self.generation}

    def search(self, q, top, kind=None, clarification_text=None):
        terms = set(re.findall(r"\w+", (q + " " + (clarification_text or "")).casefold()))
        ranked = []
        for item in self.materials:
            if kind and item.kind != kind:
                continue
            text = f"{item.title} {item.description} {' '.join(item.topics)}".casefold()
            score = sum(term in text for term in terms)
            if score:
                ranked.append((score, item.entity_key))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]))
        return {
            "generation": self.generation,
            "results": [{"entity_key": key} for _, key in ranked[:top]],
            "alternatives": [],
            "clarification": None,
        }

    def recommend(self, generation, categories, viewed, completed=None):
        facets = {
            "business": "Бизнес",
            "finance": "Финансы",
            "team": "Команда",
            "marketing": "Маркетинг",
            "technology": "Технологии",
        }
        interests = {facets[c] for c in categories}
        interests.update(t for m in self.materials if m.entity_key in viewed for t in m.topics)
        items = [
            {"entity_key": m.entity_key}
            for m in self.materials
            if m.entity_key not in viewed and interests.intersection(m.topics)
        ]
        if completed is None:
            return {"generation": generation, "results": items[:5]}
        return {
            "generation": generation,
            "status": "partial" if items and viewed else "needs_activity",
            "steps": [{"number": i + 1, "material": item} for i, item in enumerate(items[:3])]
            if viewed
            else [],
        }
