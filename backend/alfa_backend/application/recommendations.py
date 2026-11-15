"""Rules for translating model output into cards safe for a user."""


class StaleGeneration(Exception):
    pass


class InvalidModelResponse(Exception):
    pass


def require_generation(actual: str, expected: str) -> None:
    if actual != expected:
        raise StaleGeneration("Catalog generation changed; refresh catalog and retry")


def validate_list(payload: dict, generation: str, field: str) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get(field), list):
        raise InvalidModelResponse("Invalid recommendation response")
    require_generation(payload.get("generation"), generation)
    if any(not isinstance(item, dict) for item in payload[field]):
        raise InvalidModelResponse("Invalid recommendation items")
    return payload[field]


def select_cards(items: list[dict], allowed: dict, limit: int, render) -> list[dict]:
    result, seen = [], set()
    for item in items:
        key = item.get("entity_key")
        if key in allowed and key not in seen:
            result.append(render(allowed[key]))
            seen.add(key)
        if len(result) >= limit:
            break
    return result
