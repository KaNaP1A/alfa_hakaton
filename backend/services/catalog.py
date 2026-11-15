from __future__ import annotations

from domain.commands import Kind
from domain.entities import Material, User
from domain.ports import (
    CatalogRepository,
)
from domain.responses import (
    CatalogResponse,
)
from services.cards import card


class CatalogService:
    def __init__(self, repository: CatalogRepository) -> None:
        self.repository = repository

    def context(self, user: User) -> tuple[str, dict[str, Material]]:
        current = self.repository.generation()
        return current, self.repository.visible_materials(user.id, current)

    def catalog(
        self, q: str, kind: Kind | None, limit: int, offset: int, user: User
    ) -> CatalogResponse:
        current, allowed = self.context(user)
        matches = [
            m
            for m in allowed.values()
            if q.casefold() in m.title.casefold() and (kind is None or m.kind == kind)
        ]
        matches.sort(key=lambda m: (m.title, m.entity_key))
        return {
            "generation": current,
            "items": [card(m) for m in matches[offset : offset + limit]],
            "total": len(matches),
        }
