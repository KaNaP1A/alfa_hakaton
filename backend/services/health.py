from __future__ import annotations

from domain.errors import UpstreamError
from domain.ports import (
    CatalogRepository,
    RecommendationPort,
)
from domain.responses import (
    HealthResponse,
)
from services.validation import check_generation


class HealthService:
    def __init__(
        self, catalog: CatalogRepository, upstream: RecommendationPort | None, mode: str
    ) -> None:
        self.repository = catalog
        self.upstream = upstream
        self.mode = mode

    def health(self) -> HealthResponse:
        return {
            "status": "ok",
            "mode": self.mode,
            "demo": self.mode == "demo",
            "generation": self.repository.generation(),
        }

    def ready(self) -> HealthResponse:
        current = self.repository.generation()
        if self.upstream:
            state = self.upstream.health()
            if state.get("status") != "ok":
                raise UpstreamError(503, "Algorithm is not ready")
            check_generation(state.get("generation"), current)
            if self.mode in {"http", "python"} and state.get("default_search_mode") != "relevance":
                raise UpstreamError(503, "Algorithm must use relevance mode")
            if state.get("relevance_available") is False or (
                self.mode in {"http", "python"} and state.get("relevance_available") is not True
            ):
                raise UpstreamError(503, "Relevance artifacts unavailable")
        return {
            "status": "ready",
            "mode": self.mode,
            "generation": current,
            "note": "Readiness does not replace a real search smoke test",
        }
