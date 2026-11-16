from __future__ import annotations

from domain.entities import Material
from domain.responses import MaterialCard, Price
from domain.types import JsonObject


def card(material: Material) -> MaterialCard:
    price: Price
    if material.price_amount is not None and material.price_currency is not None:
        price = {
            "status": "known",
            "amount": material.price_amount,
            "currency": material.price_currency,
        }
    elif material.conditional_price_rub is not None:
        price = {
            "status": "conditional",
            "amount": str(material.conditional_price_rub),
            "currency": "RUB",
        }
    else:
        price = {"status": "unknown", "amount": None, "currency": None}
    return {
        "entity_key": material.entity_key,
        "generation": material.generation,
        "kind": material.kind,
        "title": material.title,
        "description": material.description,
        "topics": material.topics,
        "canonical_url": material.canonical_url,
        "access_type": material.access,
        "access_verified": material.access_verified,
        "price": price,
        "source_url": material.source_url,
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
