from pydantic import JsonValue

JsonObject = dict[str, JsonValue]
__all__ = ["JsonObject", "JsonValue"]
