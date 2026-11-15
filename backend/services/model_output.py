"""Allowlist model presentation fields against the current authorized catalog."""

import base64
import json

from domain.entities import Material
from domain.responses import ClarificationOption, Completion, Confidence
from domain.types import JsonObject


def suggestions(
    values: list[JsonObject], allowed: dict[str, Material], generation: str
) -> list[Completion]:
    result: list[Completion] = []
    topics = {topic for material in allowed.values() for topic in material.topics}
    for value in values:
        evidence = value.get("evidence_entity_keys")
        identifier, label, kind = value.get("id"), value.get("label"), value.get("kind")
        # Evidence is truncated by the model; never infer full visibility from a partial sample.
        if (
            not isinstance(evidence, list)
            or not evidence
            or value.get("support_count") != len(evidence)
        ):
            continue
        if not all(isinstance(key, str) and key in allowed for key in evidence):
            continue
        key = evidence[0]
        if (
            not isinstance(key, str)
            or not isinstance(identifier, str)
            or not isinstance(label, str)
            or not isinstance(kind, str)
        ):
            continue
        trusted_label = (
            allowed[key].title if kind == "title" else label if label in topics else None
        )
        if trusted_label is not None:
            result.append(
                {
                    "label": trusted_label,
                    "entity_key": key,
                    "id": identifier,
                    "kind": kind,
                    "selection_generation": generation,
                }
            )
    return result


def clarification_option(
    value: JsonObject, allowed: dict[str, Material], generation: str
) -> ClarificationOption | None:
    token = value.get("token")
    if not isinstance(token, str) or len(token) > 2048:
        return None
    try:
        raw = base64.b64decode(token, altchars=b"-_", validate=True)
        data = json.loads(raw[32:])
    except (ValueError, UnicodeError):
        return None
    if not isinstance(data, dict) or data.get("generation") != generation:
        return None
    key = data.get("value")
    if not isinstance(key, str):
        return None
    if data.get("kind") == "material" and key in allowed:
        return {"label": allowed[key].title, "kind": "material", "token": token}
    if data.get("kind") == "topic" and any(key in material.topics for material in allowed.values()):
        return {"label": key, "kind": "topic", "token": token}
    return None


def confidence(payload: JsonObject, has_results: bool) -> Confidence:
    value = payload.get("confidence")
    result: Confidence = {"status": "uncertain"}
    if isinstance(value, dict) and has_results:
        status = value.get("status")
        if status in ("unvalidated", "uncertain"):
            result["status"] = str(status)
        reason = value.get("reason")
        if reason in ("unresolved_negation", "unverified_constraint", "weak_intent_match"):
            result["reason"] = str(reason)
    return result
