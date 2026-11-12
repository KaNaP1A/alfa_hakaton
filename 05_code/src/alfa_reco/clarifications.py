"""Signed, query-bound choices. A chosen material is an explicit change of focus."""

import base64
import hashlib
import hmac
import json
import secrets


class ClarificationTokens:
    def __init__(self, generation, catalog):
        self.generation = generation
        self.catalog = {item["entity_key"]: item for item in catalog}
        self.secret = secrets.token_bytes(32)

    def issue(self, query, option):
        data = {
            "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
            "generation": self.generation,
            "kind": option["kind"],
            "value": option["value"],
        }
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True).encode()
        signature = hmac.digest(self.secret, payload, "sha256")
        return base64.urlsafe_b64encode(signature + payload).decode()

    def resolve(self, query, token):
        if not isinstance(token, str) or len(token) > 2048:
            raise ValueError("Invalid clarification")
        try:
            raw = base64.b64decode(token, altchars=b"-_", validate=True)
            signature, payload = raw[:32], raw[32:]
            if not hmac.compare_digest(signature, hmac.digest(self.secret, payload, "sha256")):
                raise ValueError("Invalid signature")
            data = json.loads(payload)
            if (
                data["generation"] != self.generation
                or data["query_sha256"] != hashlib.sha256(query.encode()).hexdigest()
            ):
                raise ValueError("Stale clarification")
            if data["kind"] == "material":
                item = self.catalog[data["value"]]
                if item["kind"] == "glossary":
                    raise ValueError("Unsupported material")
                return {
                    "kind": "material",
                    "entity_key": item["entity_key"],
                    "label": item["title"],
                }
            if data["kind"] == "topic" and isinstance(data["value"], str):
                return {"kind": "topic", "label": data["value"]}
        except (ValueError, TypeError, KeyError, UnicodeError) as error:
            raise ValueError(
                "Уточнение устарело. Повторите поиск и выберите вариант заново."
            ) from error
        raise ValueError("Invalid clarification kind")
