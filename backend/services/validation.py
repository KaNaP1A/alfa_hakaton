from domain.errors import AppError
from domain.types import JsonValue


def check_generation(actual: JsonValue, expected: str) -> None:
    if actual != expected:
        raise AppError(409, "Catalog generation changed; refresh catalog and retry")
