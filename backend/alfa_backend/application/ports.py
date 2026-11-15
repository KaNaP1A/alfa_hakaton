"""Interfaces the use cases need; transport and storage live in adapters."""

from typing import Protocol


class RecommendationPort(Protocol):
    def health(self) -> dict: ...
    def search(
        self, q: str, top: int, kind: str | None = None, clarification_text: str | None = None
    ) -> dict: ...
    def recommend(
        self,
        generation: str,
        categories: list[str],
        viewed: list[str],
        completed: list[str] | None = None,
    ) -> dict: ...
    def close(self) -> None: ...


class MaterialPort(Protocol):
    def generation(self, db) -> str: ...
    def visible_materials(self, db, user_id: str, generation: str) -> dict: ...
    def history(self, db, user_id: str, generation: str, allowed: dict) -> tuple[list, list]: ...
