from __future__ import annotations

from domain.entities import Material, User
from domain.errors import UpstreamError
from domain.ports import DemoFactory, RecommendationPort
from domain.types import JsonObject
from services.catalog import CatalogService
from services.validation import check_generation


class RecommendationContext:
    def __init__(
        self,
        catalog: CatalogService,
        upstream: RecommendationPort | None,
        demo_factory: DemoFactory,
        mode: str,
    ) -> None:
        self.catalog = catalog
        self.upstream = upstream
        self.demo_factory = demo_factory
        self.mode = mode

    def context(self, user: User) -> tuple[str, dict[str, Material], RecommendationPort]:
        current, allowed = self.catalog.context(user)
        service = self.upstream or self.demo_factory(list(allowed.values()), current)
        return (current, allowed, service)

    def validate_payload(self, payload: JsonObject, current: str, field: str) -> list[JsonObject]:
        values = payload.get(field)
        if not isinstance(values, list):
            raise UpstreamError(502, "Invalid recommendation response")
        check_generation(payload.get("generation"), current)
        result: list[JsonObject] = []
        for value in values:
            if not isinstance(value, dict):
                raise UpstreamError(502, "Invalid recommendation items")
            result.append(value)
        return result
