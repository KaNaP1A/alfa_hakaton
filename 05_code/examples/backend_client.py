"""Пример вызова локального поискового сервиса из бэкенда сайта.

Это клиент существующего прототипа, а не публичный сервер и не слой авторизации.
"""

import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class RecommendationClient:
    def __init__(self, base_url="http://127.0.0.1:8000", timeout=30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, path, *, params=None, body=None):
        url = self.base_url + path
        if params:
            url += "?" + urlencode(
                {key: value for key, value in params.items() if value is not None}
            )
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {} if data is None else {"Content-Type": "application/json"}
        request = Request(url, data=data, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as error:
            message = json.load(error).get("error", "Search service error")
            raise RuntimeError(f"Search service returned HTTP {error.code}: {message}") from error

    def health(self):
        return self._request("/health")

    def suggest(self, query, limit=6):
        return self._request("/suggest", params={"q": query, "limit": limit})

    def search(
        self,
        query,
        *,
        top=5,
        kind=None,
        selection_id=None,
        selection_generation=None,
        clarification_token=None,
        clarification_text=None,
    ):
        return self._request(
            "/search",
            params={
                "q": query,
                "mode": "relevance",
                "top": top,
                "kind": kind,
                "selection_id": selection_id,
                "selection_generation": selection_generation,
                "clarification_token": clarification_token,
                "clarification_text": clarification_text,
            },
        )

    def recommend(self, generation, categories, viewed):
        return self._request(
            "/recommend",
            body={"generation": generation, "categories": categories, "viewed": viewed},
        )

    def development_plan(self, generation, categories, viewed, completed):
        return self._request(
            "/development-plan",
            body={
                "generation": generation,
                "categories": categories,
                "viewed": viewed,
                "completed": completed,
            },
        )
