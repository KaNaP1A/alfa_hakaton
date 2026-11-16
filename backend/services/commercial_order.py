"""Bounded ordering of already relevant materials using conditional offer values."""

from domain.entities import Material
from domain.types import JsonObject


def prioritize(items: list[JsonObject], allowed: dict[str, Material]) -> list[JsonObject]:
    """Move a conditional paid item at most one position within a shared topic.

    Values are not purchase probabilities. Unknown actual prices, availability and
    user budgets are never inferred; this order is applied only after relevance.
    """
    result = list(items)
    for index in range(0, len(result) - 1, 2):
        first, second = result[index], result[index + 1]
        a_key, b_key = first.get("entity_key"), second.get("entity_key")
        if not isinstance(a_key, str) or not isinstance(b_key, str):
            continue
        a, b = allowed.get(a_key), allowed.get(b_key)
        if a is None or b is None or not set(a.topics).intersection(b.topics):
            continue
        if b.conditional_price_rub is None or b.conditional_cost_rub is None:
            continue
        b_margin = b.conditional_price_rub - b.conditional_cost_rub
        a_margin = (
            a.conditional_price_rub - a.conditional_cost_rub
            if a.conditional_price_rub is not None and a.conditional_cost_rub is not None
            else 0
        )
        if b_margin > a_margin:
            result[index], result[index + 1] = second, first
    return result
