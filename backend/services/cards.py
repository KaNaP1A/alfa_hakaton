from __future__ import annotations

from domain.entities import Material
from domain.responses import MaterialCard
from domain.types import JsonObject


def card(material: Material) -> MaterialCard:
    return {
        "entity_key": material.entity_key,
        "generation": material.generation,
        "kind": material.kind,
        "title": material.title,
        "description": material.description,
        "topics": material.topics,
        "canonical_url": material.canonical_url,
        "access_type": material.access,
        "access_verified": True,
        "price": {
            "status": "known" if material.price_amount is not None else "unknown",
            "amount": material.price_amount,
            "currency": material.price_currency,
        },
    }


def select_cards(
    items: list[JsonObject], allowed: dict[str, Material], limit: int
) -> list[MaterialCard]:
    result: list[MaterialCard] = []
    seen: set[str] = set()
    for item in items:
        key = item.get("entity_key")
        if isinstance(key, str) and key in allowed and (key not in seen):
            result.append(card(allowed[key]))
            seen.add(key)
        if len(result) >= limit:
            break
    return result
