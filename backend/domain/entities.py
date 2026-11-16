from dataclasses import dataclass

from domain.types import JsonValue


@dataclass
class User:
    id: str
    username: str
    password_hash: str
    profile: dict[str, JsonValue]


@dataclass
class Material:
    entity_key: str
    generation: str
    kind: str
    title: str
    description: str
    topics: list[str]
    published: bool
    access: str
    canonical_url: str | None
    price_amount: str | None
    price_currency: str | None
    access_verified: bool = True
    source_url: str | None = None
    conditional_price_rub: int | None = None
    conditional_cost_rub: int | None = None


@dataclass
class Activity:
    id: int
    user_id: str
    event_id: str
    generation: str
    entity_key: str
    action: str
    position: int | None
    source: str
    created_at: float
